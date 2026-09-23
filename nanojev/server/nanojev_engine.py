#!/usr/bin/env python3
"""NanoJev 本地推理引擎 —— Apple Silicon（MPS / CPU）适配版。

背景
----
NanoJev 官方推理入口 `predict_toy_decisions.DecisionPredictor` 硬编码 CUDA：

    if device.type != "cuda" or not torch.cuda.is_available():
        raise ValueError("此原型推理入口需要可用CUDA设备；本命令未启用CPU或远程回退")
    torch.autocast("cuda", dtype=torch.bfloat16, ...)

本机是 MacBook-Air M4（arm64，无 CUDA），因此必须替换设备与精度处理。

保持不变（直接复用官方实现，保证数值与官方一致）
------------------------------------------------
  - `validate_request`            请求校验
  - `prepare_examples`            状态/问题/候选 → token 序列（前缀构造规则）
  - `answer_from_probabilities`   概率 → 答案（choice / boolean / score）
  - `DecisionModel`               模型结构（从 train_toy_decisions.py 动态载入）

被替换（本模块的唯一差异点）
----------------------------
  - 设备选择：mps 优先，退回 cpu（原版只允许 cuda）
  - 精度：默认 mps→float16 / cpu→float32（原版强制 bf16 autocast）
  - 去掉 torch.cuda.* 全部调用

注意：`state` 字段训练时是**纯文本字符串**（不是 JSON 对象）。
本引擎不做任何改写，调用方需自行序列化好。
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys
import time
from pathlib import Path

# 官方推理脚本在网络关闭状态下运行；保持一致，避免任何隐式下载。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import predict_toy_decisions as ptd  # noqa: E402  （复用官方校验/编码/解码逻辑）

_DTYPE_MAP = {}


def _load_decision_model_class():
    """从官方 trainer 动态载入 DecisionModel 定义（不执行其 main）。"""
    path = _SRC / "train_toy_decisions.py"
    spec = importlib.util.spec_from_file_location("nanojev_trainer_for_inference", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法载入 DecisionModel 定义：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DecisionModel


def pick_device(preference: str = "auto") -> str:
    """设备选择：auto 时 MPS 优先，退回 CPU。"""
    import torch

    if preference and preference != "auto":
        return preference
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    return "cpu"


class NanoJevEngine:
    """本地持久推理对象：构造时加载一次权重，之后每次 predict 复用。"""

    def __init__(
        self,
        checkpoint_dir: str,
        device: str = "auto",
        dtype: str | None = None,
        max_length: int | None = None,
    ):
        import torch
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModel, AutoTokenizer

        _DTYPE_MAP.update(
            {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
        )

        root, paths = ptd.local_checkpoint_files(checkpoint_dir)
        run_config = ptd.read_json(paths["run_config"])
        set_head = run_config.get("set_head")
        if set_head not in {"none", "attention"}:
            raise ValueError("checkpoint config 缺少合法 set_head")

        self.device_name = pick_device(device)
        self.device = torch.device(self.device_name)

        # 精度：MPS 上 float16 明显快于 float32；CPU 上 float32 才稳。
        if dtype in (None, "auto"):
            dtype = "float16" if self.device_name == "mps" else "float32"
        if dtype not in _DTYPE_MAP:
            raise ValueError(f"不支持的 dtype：{dtype}")
        self.dtype_name = dtype
        self.dtype = _DTYPE_MAP[dtype]

        tokenizer = AutoTokenizer.from_pretrained(
            str(paths["tokenizer"]), local_files_only=True, trust_remote_code=False
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token

        body_config = AutoConfig.from_pretrained(
            str(paths["body_config"]), local_files_only=True, trust_remote_code=False
        )
        body_config.use_cache = False

        limit = run_config.get("max_length", 512) if max_length is None else max_length
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("max_length 必须为正整数")
        ctx = getattr(body_config, "max_position_embeddings", None)
        if isinstance(ctx, int) and limit > ctx:
            raise ValueError("max_length 超过 backbone 上下文长度")

        # from_config 只构造结构；参数完全由 best.safetensors 提供。
        try:
            body = AutoModel.from_config(
                body_config, attn_implementation="sdpa", trust_remote_code=False
            )
        except Exception:
            # 个别 MPS 版本对 sdpa 支持不全，退回 eager。
            body = AutoModel.from_config(
                body_config, attn_implementation="eager", trust_remote_code=False
            )

        DecisionModel = _load_decision_model_class()
        model = DecisionModel(body, set_head)

        weights = load_file(str(paths["weights"]), device="cpu")
        missing, unexpected = model.load_state_dict(weights, strict=False)
        if missing or unexpected:
            raise ValueError(
                "权重与模型结构不匹配："
                f"missing={list(missing)[:6]} unexpected={list(unexpected)[:6]}"
            )
        del weights

        model.to(device=self.device, dtype=self.dtype)
        model.eval()

        self.model = model
        self.tokenizer = tokenizer
        self.root = root
        self.run_config = run_config
        self.limit = limit
        self._torch = torch
        self.inference_calls = 0
        self.weights_bytes = paths["weights"].stat().st_size

    # ------------------------------------------------------------------ info
    def info(self) -> dict:
        return {
            "device": self.device_name,
            "dtype": self.dtype_name,
            "set_head": self.run_config.get("set_head"),
            "base_model": self.run_config.get("model"),
            "base_revision": self.run_config.get("resolved_model_revision"),
            "max_length": self.limit,
            "parameter_storage": self.run_config.get("parameter_storage"),
            "weights_bytes": self.weights_bytes,
            "inference_calls": self.inference_calls,
        }

    # --------------------------------------------------------------- predict
    def predict(self, payload: dict, temperature: float = 1.0, batch_questions: int = 0) -> dict:
        """payload 形如 {"states": [{"id","state","questions"}, ...]}。

        与官方唯一的差别：不做 cuda autocast，只在目标设备上跑。
        """
        torch = self._torch

        states = ptd.validate_request(payload)
        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or not math.isfinite(temperature)
            or temperature <= 0
        ):
            raise ValueError("temperature 必须为有限正数")

        examples = ptd.prepare_examples(payload, self.tokenizer, self.limit)
        batches = ptd.complete_question_batches(examples, batch_questions)

        self.inference_calls += 1
        started = time.perf_counter()
        outputs = {s["id"]: {"id": s["id"], "answers": {}} for s in states}

        self.model.eval()
        with torch.inference_mode():
            for batch in batches:
                logits, _valid = self.model(batch, self.tokenizer.pad_token_id)
                for i, example in enumerate(batch):
                    k = len(example["candidate_ids"])
                    scores = logits[i][:k].float()
                    if not torch.isfinite(scores).all():
                        raise ValueError("模型产生非有限 logits，未返回部分预测")
                    probs = (scores / temperature).softmax(-1).cpu().tolist()
                    outputs[example["state_id"]]["answers"][example["qid"]] = (
                        ptd.answer_from_probabilities(example, probs)
                    )
        elapsed = time.perf_counter() - started

        return {
            "schema_version": "nanojev-local-inference-v1",
            "checkpoint": {
                "directory": str(self.root),
                "base_model": self.run_config.get("model"),
                "set_head": self.run_config["set_head"],
            },
            "execution": {
                "device": self.device_name,
                "dtype": self.dtype_name,
                # 与原版 execution 字段同义，便于对照
                "states": len(states),
                "questions": len(examples),
                "candidate_leaves": sum(len(ex["leaf_tokens"]) for ex in examples),
                "total_prefill_tokens": sum(
                    sum(len(t) for t in ex["leaf_tokens"]) for ex in examples
                ),
                "forward_passes": len(batches),
                "server_seconds": elapsed,
                "autoregressive_decode_steps": 0,
                "prefix_sharing": False,
                "network_model_calls": 0,
                "persistent_model_load_count": 1,
                "inference_call_index": self.inference_calls,
            },
            "states": list(outputs.values()),
        }


# --------------------------------------------------------------------- CLI
def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--input", required=True, help="含 states 数组的 JSON 文件")
    parser.add_argument("--device", default="auto", help="auto | mps | cpu")
    parser.add_argument("--dtype", default="auto", help="auto | float32 | float16 | bfloat16")
    parser.add_argument("--max-length", type=int)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    engine = NanoJevEngine(
        args.checkpoint_dir, device=args.device, dtype=args.dtype, max_length=args.max_length
    )
    print(json.dumps({"loaded": engine.info()}, ensure_ascii=False, indent=2), flush=True)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = engine.predict(payload, temperature=args.temperature)
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(json.dumps({"output": args.output, "execution": result["execution"]},
                         ensure_ascii=False, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    main()

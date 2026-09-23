#!/usr/bin/env python3
"""NanoJev 本地决策服务 —— 对安卓 App 提供与 OpenRouter 同形的 /api/alpha/decisions。

为什么要做协议兼容
------------------
安卓 app 的 `JevClient.kt` 直接 POST 到 OpenRouter 的 `/api/alpha/decisions`，
请求体是 `{model, state, questions}`，应答读 `answers[qid]`。

本服务在 Mac 上提供**同形接口**，于是 app 侧只需把 base URL 从
`https://openrouter.ai` 换成本机地址，其余业务逻辑（题目集、悬浮窗、
候选排序、回填输入框）一行都不用改。

三方字段差异（已在本服务内抹平）
--------------------------------
| 项目        | Jev 线上协议(typesafe)      | NanoJev 本地                | 本服务输出        |
|-------------|------------------------------|------------------------------|-------------------|
| 二值题类型  | `noul`                       | `boolean`                    | 收 `noul` 转 `boolean` |
| 二值题答案  | `{noul: p}`                  | `{p_true: p}`                | 还原成 `{noul: p}` |
| choice 答案 | `{choice, confidence, probs}`| `{choice, probabilities}`    | 补 `confidence`   |
| score 答案  | `{score, confidence, legend}`| `{score, level, probs}`      | 补 `confidence`/`legend` |
| state       | JSON 对象（app 现状）        | 纯文本字符串（训练格式）     | 自动序列化为文本  |

`confidence` 与 `legend` 在 NanoJev 侧不存在，本服务按明确规则补出：
  - confidence = 该题概率分布的最大值（代理值，非官方校准量）
  - legend     = {等级序号: 等级原文}，供 app 推算 maxLevel

用法
----
  python jev_server.py --checkpoint-dir ../checkpoints/NanoJev-unified --port 8788
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nanojev_engine import NanoJevEngine  # noqa: E402

MAX_BODY = 2_000_000
_INFER_LOCK = threading.Lock()  # torch/MPS 推理串行化，避免并发争用

# Jev 协议里二值题的题型名 → NanoJev 题型名
_TYPE_IN = {"noul": "boolean", "boolean": "boolean", "choice": "choice", "score": "score"}


def state_to_text(state) -> str:
    """把 app 传来的 state 转成训练时的纯文本形态。

    训练数据里 state 是一句话式的紧凑文本（例：
    `Home log: user wants the dining room fan set to on; access=yes; occupants=2.`）。
    app 现在传的是 {"chat": {"relationship","messages","latest_from"}}，
    这里按同样的紧凑风格压平成文本。
    """
    if isinstance(state, str):
        return state

    if isinstance(state, dict) and isinstance(state.get("chat"), dict):
        chat = state["chat"]
        rel = str(chat.get("relationship") or "").strip()
        latest = str(chat.get("latest_from") or "other").strip()
        head = f"Chat log: relationship={rel or 'unspecified'}; latest_from={latest}."
        lines = [head]
        for m in chat.get("messages") or []:
            if isinstance(m, dict):
                who = str(m.get("from") or "other")
                text = str(m.get("text") or "").replace("\n", " ").strip()
                if text:
                    lines.append(f"{who}: {text}")
        return "\n".join(lines)

    if isinstance(state, (dict, list)):
        return json.dumps(state, ensure_ascii=False, separators=(",", ":"))

    return str(state)


def translate_questions_in(questions: dict) -> dict:
    """app 的题目集 → NanoJev 题目集（noul → boolean）。"""
    out = {}
    for qid, q in questions.items():
        if not isinstance(q, dict):
            raise ValueError(f"题目 {qid} 必须是对象")
        jtype = q.get("type")
        if jtype not in _TYPE_IN:
            raise ValueError(f"题目 {qid} 题型不支持：{jtype}")
        ntype = _TYPE_IN[jtype]
        item = {"type": ntype, "instructions": q.get("instructions", "")}
        criteria = q.get("criteria")
        if ntype == "boolean":
            # 保留 {false,true} 的描述文本；NanoJev 认这个键名
            if isinstance(criteria, dict):
                clean = {k: v for k, v in criteria.items() if k in ("false", "true") and v}
                if clean:
                    item["criteria"] = clean
        else:
            if criteria is None:
                raise ValueError(f"题目 {qid} 缺少 criteria")
            item["criteria"] = criteria
        out[qid] = item
    return out


def translate_answers_out(answers: dict, original_questions: dict) -> dict:
    """NanoJev 答案 → Jev 线上协议形态。"""
    out = {}
    for qid, ans in answers.items():
        jtype = (original_questions.get(qid) or {}).get("type")
        probs = ans.get("probabilities") or {}
        confidence = max(probs.values()) if probs else 0.0

        if jtype == "noul":
            # app 读 answers[qid].noul
            out[qid] = {"noul": float(ans.get("p_true", 0.0)), "confidence": confidence,
                        "probabilities": probs}
        elif jtype == "score":
            criteria = (original_questions.get(qid) or {}).get("criteria") or []
            legend = {str(i): str(t) for i, t in enumerate(criteria)}
            out[qid] = {
                "score": float(ans.get("score", 0.0)),
                "confidence": confidence,
                "legend": legend,
                "probabilities": probs,
            }
        else:  # choice
            out[qid] = {
                "choice": ans.get("choice"),
                "confidence": confidence,
                "probabilities": probs,
            }
    return out


def build_handler(engine: NanoJevEngine, token: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "NanoJev-Local/1.0"
        protocol_version = "HTTP/1.1"

        # ------------------------------------------------------------ helpers
        def _send(self, code: int, payload: bytes, mime="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"))

        def _authed(self) -> bool:
            if not token:
                return True
            got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            return got == token

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                raise ValueError(f"请求体长度非法：{length}")
            return json.loads(self.rfile.read(length).decode("utf-8"))

        # --------------------------------------------------------------- GET
        def do_GET(self):
            if self.path.split("?")[0] in ("/health", "/api/health"):
                # your_ip 回显调用方地址：手机上打开这一页就能看到自己是从哪个 IP 连过来的
                self._json(200, {
                    "ready": True,
                    "provider_calls": 0,
                    "your_ip": self.client_address[0],
                    **engine.info(),
                })
                return
            if self.path.split("?")[0] == "/":
                self._json(200, {
                    "service": "NanoJev 本地决策服务",
                    "endpoints": {
                        "GET /health": "健康检查与运行时信息",
                        "POST /api/alpha/decisions": "Jev 兼容接口（安卓 app 直接指向此处）",
                        "POST /api/evaluate": "NanoJev 原生接口 {states:[...]}",
                    },
                    "runtime": engine.info(),
                })
                return
            self._json(404, {"error": "Not found"})

        # -------------------------------------------------------------- POST
        def do_POST(self):
            route = self.path.split("?")[0]
            try:
                if not self._authed():
                    self._json(401, {"error": "服务端令牌校验失败"})
                    return
                body = self._read_body()

                if route == "/api/alpha/decisions":
                    self._handle_jev(body)
                elif route == "/api/evaluate":
                    self._handle_native(body)
                else:
                    self._json(404, {"error": f"未知接口：{route}"})
            except (ValueError, TypeError, KeyError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"本地推理失败：{type(exc).__name__}: {exc}"})

        # -------------------------------------------- Jev 兼容（app 实际调用）
        def _handle_jev(self, body: dict):
            t0 = time.perf_counter()

            nested = isinstance(body.get("state"), dict) and isinstance(
                body["state"].get("chat"), dict
            )
            if nested:
                # app 的真实形态：{"state": {"chat": {...}}, "questions": {...}}
                questions = body.get("questions")
                if not isinstance(questions, dict) or not questions:
                    raise ValueError("questions 必须是非空对象")
                payload = {"states": [{
                    "id": "s1",
                    "state": state_to_text(body["state"]),
                    "questions": translate_questions_in(questions),
                }]}
            else:
                # 兼容 NanoJev 形制 {"states":[{"id","state","questions"}, ...]}
                states = body.get("states")
                if not isinstance(states, list) or not states:
                    raise ValueError("缺少 state 或 states")
                for i, s in enumerate(states):
                    if not isinstance(s, dict):
                        raise ValueError(f"states[{i}] 必须是对象")
                    qs = s.get("questions")
                    if not isinstance(qs, dict) or not qs:
                        raise ValueError(f"states[{i}].questions 必须是非空对象")
                questions = {
                    qid: q
                    for s in states
                    for qid, q in s["questions"].items()
                }
                payload = {"states": [{
                    "id": s.get("id") or f"s{i}",
                    "state": state_to_text(s.get("state")),
                    "questions": translate_questions_in(s["questions"]),
                } for i, s in enumerate(states)]}

            with _INFER_LOCK:
                result = engine.predict(payload)

            # app 只发一个 state，答案直接平铺；多 state 时按 id 分组返回。
            if len(result["states"]) == 1:
                outgoing = translate_answers_out(result["states"][0]["answers"], questions)
            else:
                outgoing = {
                    s["id"]: translate_answers_out(s["answers"], questions)
                    for s in result["states"]
                }

            elapsed = time.perf_counter() - t0
            ex = dict(result["execution"])
            ex["client_roundtrip_seconds"] = elapsed
            print(
                f"[decisions] {ex['questions']} 题 / {ex['candidate_leaves']} 候选路径 / "
                f"{ex['total_prefill_tokens']} tokens / 设备={ex['device']} / "
                f"推理={ex['server_seconds']:.2f}s / 全程={elapsed:.2f}s",
                flush=True,
            )
            self._json(200, {
                "model": body.get("model") or "nanojev-local",
                "answers": outgoing,
                "execution": ex,
            })

        # ------------------------------------------------- NanoJev 原生直通
        def _handle_native(self, body: dict):
            with _INFER_LOCK:
                result = engine.predict(body)
            self._json(200, result)

        def log_request(self, code="-", size="-"):
            # 记录时间 + 客户端 IP + 方法 + 路径 + 状态码，便于判断"手机到底有没有连上"。
            # 不落任何对话内容。
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[http] {ts} {self.client_address[0]:<15} "
                f"{self.command} {self.path} -> {code}",
                flush=True,
            )

        def log_message(self, fmt, *args):
            # 仅错误/异常路径会走到这里（正常请求已被 log_request 接管）
            print(f"[http] {time.strftime('%H:%M:%S')} {fmt % args}", flush=True)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--host", default="0.0.0.0", help="默认 0.0.0.0，手机同一 WiFi 可访问")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--device", default="auto", help="auto | mps | cpu")
    parser.add_argument("--dtype", default="auto", help="auto | float32 | float16 | bfloat16")
    parser.add_argument("--max-length", type=int)
    parser.add_argument("--token", default=None, help="可选：要求 Bearer 令牌")
    args = parser.parse_args()

    print("[启动] 正在加载 NanoJev 权重……", flush=True)
    t0 = time.perf_counter()
    engine = NanoJevEngine(
        args.checkpoint_dir, device=args.device, dtype=args.dtype, max_length=args.max_length
    )
    print(f"[启动] 加载完成，用时 {time.perf_counter() - t0:.1f}s", flush=True)
    print(json.dumps(engine.info(), ensure_ascii=False, indent=2), flush=True)

    httpd = ThreadingHTTPServer((args.host, args.port), build_handler(engine, args.token))
    print(json.dumps({
        "url": f"http://{args.host}:{args.port}",
        "ready": True,
        "provider_calls": 0,
    }, ensure_ascii=False), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

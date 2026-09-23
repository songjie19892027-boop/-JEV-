#!/usr/bin/env python3
"""用用户截图里的那轮真实对话跑一次推理，输出真实概率，用于前端版式预览。

对话逐字取自用户提供的微信截图（最后一屏），共 9 条 —— 正好是
JevQuestions.buildState 会取的最大长度（last 10）。

输出：完整 answers JSON，供渲染预览页使用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_local as v  # noqa: E402

URL = "http://127.0.0.1:8788/api/alpha/decisions"

# 逐字取自截图。side: "me" = 右侧绿色气泡（用户），"other" = 左侧对方。
MESSAGES = [
    ("other", "你今天是不是又忘了跟我说过什么？"),
    ("me", "记得，你先别提示我，让我自己说。"),
    ("other", "那你先说。"),
    ("me", "等一下，我想说完整一点。"),
    ("other", "你最好是。"),
    ("me", "我想起来了。你昨天跟我说周末想出去吃饭，而且你不想每次都是你来安排。"),
    ("other", "所以呢？"),
    ("me", "所以这次我来安排，餐厅和时间我定好再告诉你，你只负责去。"),
    ("other", "这还差不多。"),
]

CANDIDATES = [
    "好，我这就把餐厅定下来发你",
    "嗯，这次我来安排，你放心",
    "那你说想吃什么，我照着订",
]

payload = v.build_payload(
    "对方是我的伴侣；from=me 的是我发的，from=other 的是对方发的",
    MESSAGES,
    CANDIDATES,
)

out, elapsed = v.call(URL, payload, 1200)
ex = out.get("execution", {})

print("elapsed_seconds =", round(elapsed, 2))
print("forward_passes  =", ex.get("forward_passes"))
print("prefill_tokens  =", ex.get("total_prefill_tokens"))
print("=" * 70)
print(json.dumps(out.get("answers", {}), ensure_ascii=False, indent=2))

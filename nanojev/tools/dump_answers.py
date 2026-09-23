#!/usr/bin/env python3
"""打一次真实请求，把 answers 的完整结构 dump 出来。

用途：前端要渲染「问题 → 各选项百分比」，必须先确认每一类答案
（noul / score / choice）里到底有哪些字段，尤其是 choice 的
`probabilities` 是否真的带全量分布、score 的 `legend` 是什么形状。

题目与状态逐字复用 verify_local.py，保证与真机请求同形。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_local as v  # noqa: E402

URL = "http://127.0.0.1:8788/api/alpha/decisions"

payload = v.build_payload(
    "对方是我的伴侣；from=me 的是我发的，from=other 的是对方发的",
    v.DEFAULT_MESSAGES,
    v.DEFAULT_CANDIDATES,
)

out, elapsed = v.call(URL, payload, 1200)
answers = out.get("answers", {})

print("elapsed_seconds =", round(elapsed, 2))
print("fields_per_answer:")
for qid, ans in answers.items():
    print(f"  {qid:<18} {sorted(ans.keys())}")
print("=" * 70)
print(json.dumps(answers, ensure_ascii=False, indent=2))

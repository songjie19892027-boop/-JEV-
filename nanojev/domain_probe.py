#!/usr/bin/env python3
"""领域对照实验：同一批问题，分别喂「中文聊天状态」与「游戏状态」。

目的
----
NanoJev 的训练数据全部来自游戏（maze / snake / ViZDoom）。首次实测在中文聊天
场景下 choice 类问题置信度仅 0.18~0.33，分布接近平坦。本脚本用同一套问题、
不同领域的状态做对照，把「低置信度源于领域不匹配」这个推断变成可测量的事实。

用法
----
    python domain_probe.py --url http://127.0.0.1:8799/api/alpha/decisions
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- 复用的题目
# 精简为 3 道有代表性的题：1 道二值、2 道多选，足以看出分布是否变尖。
BOOL_Q = {
    "id": "literal_question",
    "type": "noul",
    "instructions": (
        "Does the other person's last message directly ask for information "
        "that the user has not yet given?"
    ),
}

ACTION_Q = {
    "id": "best_action",
    "type": "choice",
    "instructions": (
        "What type of next action is best? Do not decide whether to send a "
        "message immediately. Ignore timing. Choose only the action type. "
        "answer_question / ask_clarifying / apologize / give_commitment / "
        "check_history / wait_and_hold / casual_reply / offer_help / "
        "set_boundary / stop_engaging"
    ),
    "criteria": {
        "answer_question": "give the asked information",
        "ask_clarifying": "ask something back",
        "apologize": "own a mistake",
        "give_commitment": "promise a future action",
        "check_history": "verify what was said before",
        "wait_and_hold": "do nothing yet",
        "casual_reply": "light small talk",
        "offer_help": "offer to help",
        "set_boundary": "decline firmly",
        "stop_engaging": "end the thread",
    },
}

INTENT_Q = {
    "id": "true_intent",
    "type": "choice",
    "instructions": (
        "What does the other person actually want right now? "
        "answer=wants information; request_action=wants user to do something; "
        "emotional_support=wants comfort; casual_chat=just chatting; "
        "test_boundary=probing the relationship; close_topic=wants to end it"
    ),
    "criteria": {
        "answer": "wants information",
        "request_action": "wants user to do something",
        "emotional_support": "wants comfort",
        "casual_chat": "just chatting",
        "test_boundary": "probing the relationship",
        "close_topic": "wants to end it",
    },
}

QUESTIONS = {
    BOOL_Q["id"]: BOOL_Q,
    ACTION_Q["id"]: ACTION_Q,
    INTENT_Q["id"]: INTENT_Q,
}


# ------------------------------------------------------------------ 两种状态
STATE_CHAT = (
    "Chat log: relationship=对方是我的伴侣; latest_from=other.\n"
    "me: 今天有点忙\n"
    "other: 你该不会是忘了吧"
)

STATE_GAME = """Maze navigation log: agent must reach the goal without stepping on lava.
Grid 5x5. Agent at (1,1). Goal at (4,4). Lava at (2,1),(2,2),(3,3).
Steps taken: up, right. Remaining budget: 6 moves.
Cell ahead (2,1) contains lava. Alternate route via (1,2) is clear.
Previous episode: agent stepped into lava at step 3 and lost the episode."""


def build_payload(state: str) -> dict:
    """两种状态都走 `states` 直通形态（state 为纯文本），
    避免翻译层差异污染对照结果。"""
    return {"model": "nanojev-local", "states": [
        {"id": "s1", "state": state, "questions": QUESTIONS}
    ]}


def call(url: str, payload: dict, timeout: int) -> tuple[dict, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
    return data, time.perf_counter() - t0


def summarize(label: str, out: dict, elapsed: float) -> None:
    ex = out.get("execution", {})
    print(f"\n=== {label}")
    print(f"    候选路径 {ex.get('candidate_leaves')} / 预填 token "
          f"{ex.get('total_prefill_tokens')} / 推理 {elapsed:.2f}s")
    # Jev 兼容接口返回平铺 answers；原生接口返回 states[]
    if "answers" in out:
        blocks = [(None, out["answers"])]
    else:
        blocks = [(st.get("id"), st.get("answers", {})) for st in out.get("states", [])]
    for state_id, answers in blocks:
        if state_id:
            print(f"    [state {state_id}]")
        for qid, a in answers.items():
            probs = a.get("probabilities") or {}
            conf = a.get("confidence")
            if "noul" in a:
                print(f"    {qid:18s} boolean p_true={a['noul']:.4f}")
            else:
                ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:3]
                pretty = ", ".join(f"{k}={v:.3f}" for k, v in ranked)
                print(f"    {qid:18s} 选中={str(a.get('choice')):18s} "
                      f"置信={conf:.3f} | {pretty}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8799/api/alpha/decisions")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    for label, state in (("A. 中文聊天状态（app 的真实用法）", STATE_CHAT),
                         ("B. 游戏状态（NanoJev 训练域）", STATE_GAME),
                         ("C. 中文聊天状态·重复测延迟稳定性", STATE_CHAT)):
        out, el = call(args.url, build_payload(state), args.timeout)
        summarize(label, out, el)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

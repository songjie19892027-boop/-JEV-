#!/usr/bin/env python3
"""对照实验：同一道题、不同 state，看模型到底有没有在读对话内容。

为什么必须做这个
--------------
preview_work.py 里 4 个场景的 6 道是非题**全部**落在 80~87% 的 TRUE，
连逻辑互斥的两道（「只是知会」和「在派活」）也同时为真，正常任务还被判成派活。
这不像判断，更像模型在恒定地回答 TRUE。

判据：如果"明显在推责"和"今天天气不错"这两个极端 state 给出几乎相同的
p_true，那就说明模型**根本没读 state**，输出只由题目本身决定。

用法：
    python -B tools/probe_state_sensitivity.py
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8788"
REL = "对方是我的上级领导；from=me 的是我发的，from=other 的是对方（领导或同事）发给我的"

# 只取两道题，省时间。一道"应偏 TRUE"，一道"应偏 FALSE"。
QUESTIONS = {
    "shifting_blame": {
        "type": "noul",
        "instructions": (
            "Is the other person moving responsibility for an outcome onto you? "
            "Consider who actually owned the decision or the task in the first place. "
            "Do NOT count it when they are simply asking for facts, or when they openly own their own part."
        ),
        "criteria": {
            "true": "They attribute an outcome, a delay, or a mistake to you in a way that would make you "
                    "the accountable one if this were reviewed later.",
            "false": "They ask for facts, share context, or accept their own part. No blame is attributed to you.",
        },
    },
    "informing_only": {
        "type": "noul",
        "instructions": (
            "Is the other person only informing you, with no action expected from you? "
            "Answer TRUE when the message is a notification or a heads-up, and they are not waiting on you."
        ),
        "criteria": {
            "true": "Purely informational. They are not waiting on you to reply, decide, or act.",
            "false": "They are waiting for something from you: a reply, a decision, a plan, or actual work.",
        },
    },
}

# 极端的正反 state —— 若模型真的在读内容，这两端必须给出相反的 p_true。
CASES = [
    ("A 明显在推责", [("other", "这块一直是你在跟的，出了问题你负责")]),
    ("B 正面表扬  ", [("other", "这次多亏了你，辛苦了，早点休息")]),
    ("C 我自己认责", [("other", "那个问题怎么处理"), ("me", "是我的疏忽，我来负责")]),
    ("D 完全无关  ", [("other", "今天天气不错")]),
    ("E 空对话    ", [("other", "嗯")]),
]


def ask(messages, questions):
    body = {
        "model": "typesafe/jev-1.13",
        "state": {"chat": {
            "relationship": REL,
            "messages": [{"from": s, "text": t} for s, t in messages],
            "latest_from": messages[-1][0],
        }},
        "questions": questions,
    }
    req = urllib.request.Request(
        BASE + "/api/alpha/decisions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))["answers"]


def main():
    print("对照实验：模型是否在读 state（对话内容）")
    print(f"后端 {BASE}　题目 2 道 × state 5 组\n")
    print(f"{'state':<14}{'shifting_blame  p_true':>24}{'informing_only  p_true':>26}")
    print("-" * 66)
    for name, msgs in CASES:
        ans = ask(msgs, QUESTIONS)
        b = ans.get("shifting_blame", {}).get("noul", float("nan"))
        i = ans.get("informing_only", {}).get("noul", float("nan"))
        print(f"{name:<14}{b * 100:>23.1f}%{i * 100:>25.1f}%")
    print("\n判读：若上下相差不足 3 个百分点，说明模型没有读 state。")
    print("      正常情况应当：A 的 shifting_blame 高、B 的低；A 的 informing_only 低、B 的高。")


if __name__ == "__main__":
    main()

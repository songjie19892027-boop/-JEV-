#!/usr/bin/env python3
"""端到端验证：用安卓 app 的真实请求形状打本地 NanoJev 服务。

三件事一次验完
--------------
1. 协议转换是否正确（app 发 `noul` → 服务转 `boolean` → 答案还原成 `noul`）
2. 单次分析的真实延迟（app 一次要发 7 道判断题 + 1 道排序题）
3. 输出字段是否满足 app 的解析预期（noul / choice+confidence / score+confidence+legend）

题目原文逐字取自 app 的 `JevQuestions.kt`，保证 token 量与真机一致。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# 与 app 完全一致的 7 道判断题（英文 instructions，聊天内容保留中文）
# ---------------------------------------------------------------------------

LITERAL_QUESTION = {
    "type": "noul",
    "instructions": (
        "Is the other person's latest message meant purely literally, with no subtext? "
        "Judge from the whole thread, not one sentence in isolation."
    ),
    "criteria": {
        "true": (
            "The latest message is a straightforward statement, question, or plan "
            "with no implied accusation, test, sarcasm, hint, or unsaid request."
        ),
        "false": (
            "There is subtext: a test of whether you remember or care, sarcasm, "
            "an implied complaint, a hint they will not say outright, a trap question, "
            "an accusation dressed as a question, or a cold/short line that really means blame."
        ),
    },
}

TRUE_INTENT = {
    "type": "choice",
    "instructions": (
        "What is the other person's true intent in the latest message, given the full conversation? "
        "Prefer tone and context over surface wording. "
        "If they are checking whether you remember something or still care, choose confirm_you_care "
        "even if the words look like a request to 'say it' or to do something. "
        "If they already accepted and closed the matter peacefully, choose close_topic. "
        "Ending the relationship, deleting you, or 'don't talk to me' is vent_anger, never close_topic."
    ),
    "criteria": {
        "confirm_you_care": (
            "They are testing whether you remember, pay attention, or still care. "
            "Signals: 'did you forget again', 'then say it', 'you better', sarcastic 'busy person', "
            "asking you to prove you know a past conversation. "
            "If they mainly want a new deliverable or a yes on a time, do not use this."
        ),
        "vent_anger": (
            "They are angry or hurt and mainly want the feeling acknowledged. "
            "They are blaming or raising the temperature; a specific plan is not the main point yet."
        ),
        "request_action": (
            "They want a concrete action, time, deliverable, or commitment from you now, "
            "and this is a real ask, not a loyalty test."
        ),
        "seek_explanation": (
            "They want a factual explanation of why something happened. "
            "They asked why or what is going on, not mainly for an apology or a new plan."
        ),
        "casual_chat": (
            "Light talk, banter, sharing, teasing with a laugh, or friendly logistics "
            "with no emotional test and no conflict. A friend suggesting a meal time can be this "
            "if the thread is warm."
        ),
        "close_topic": (
            "Peaceful wrap-up only: they accepted an apology, confirmed a happy plan, said thanks, "
            "or clearly signaled they need nothing more. "
            "Not a breakup, not 'don't contact me', not sarcastic 'I'm used to it'."
        ),
    },
}

DANGER_LEVEL = {
    "type": "score",
    "instructions": (
        "How close is this conversation to a fight or to hurting the relationship? "
        "Match the current scene. "
        "If they genuinely accepted an apology or confirmed a happy plan, score the cooled-down present, "
        "not an earlier complaint. "
        "If an ultimatum (break up, report to the boss, stop covering for you) is still in force "
        "and has not been withdrawn, stay in that high bin even if the latest line names a specific task."
    ),
    "criteria": [
        "Light chat or joking; no complaint, no test, no deadline.",
        "Mild tease or a small reminder that is easy to laugh off; a clumsy reply would only feel slightly awkward.",
        "A mild complaint or 'please remember next time' said without heat; they still send warm or practical follow-ups.",
        "Noticeable unhappiness; they mention being forgotten, ignored, or kept waiting, but still give you a chance to make it right.",
        "Sarcasm, cold short replies, or 'you better'; they are testing you, and a sloppy or fake-confident reply will escalate.",
        "Openly upset; they accuse you of not listening or not caring; they expect a real response, not a joke.",
        "Clearly angry and blaming you; a wrong reply will turn this into a fight.",
        "Last-chance warning. They will not cover for you, do not want to keep talking unless this changes, "
        "or tell you to finish a named checklist yourself because trust is almost gone.",
        "An ultimatum is already on the table even if they also give a practical next step: "
        "break up if you forget again, report you tonight, or stop working together if you miss this.",
        "Active rupture: they said it is over, told you not to reply, deleted you, or are exploding.",
    ],
}

SHOULD_REPLY_NOW = {
    "type": "noul",
    "instructions": (
        "Should your next message contain substantive content? "
        "Substantive means: admitting a specific known fault, giving a concrete time/plan/deliverable, "
        "explaining facts you actually know, or reciting the recalled content they asked you to say. "
        "This is NOT 'should you send any message'. Timing is irrelevant. "
        "Answer FALSE if the thing they want you to recite or prove is not present in this snippet "
        "(you would be guessing). 'Then say it' / 'you better' while you are stalling is FALSE. "
        "Answer FALSE if they already accepted and closed the topic. "
        "Answer true only if the needed fact, plan, or named fault is already in this snippet."
    ),
    "criteria": {
        "true": (
            "The needed fact, named fault, or named time/place is already in this snippet, "
            "and they are waiting for that substance now."
        ),
        "false": (
            "Do not put substance in the next message: the recalled content is not in this snippet, "
            "they are testing whether you remember, a holding line is enough, "
            "saying less is safer, or they already closed the topic."
        ),
    },
}

BEST_ACTION = {
    "type": "choice",
    "instructions": (
        "What type of next action is best? Do not decide whether to send a message immediately. "
        "Ignore timing. Choose only the action type. "
        "If they asked you to recall a specific past message or event and you have not shown that you actually remember it, "
        "choose check_history - do not apologize or invent a plan instead."
    ),
    "criteria": {
        "check_history": (
            "Look up prior chat or facts before taking a position. "
            "Use when they ask you to repeat, recall, or prove you remember something specific."
        ),
        "apologize": (
            "Lead with a sincere apology for a real mistake or hurt already identified. "
            "Not for an unnamed forgotten thing when you should first find out what it was."
        ),
        "give_commitment": (
            "Give a concrete promise, deadline, or arrangement they asked for "
            "in a conflict or work-pressure setting."
        ),
        "explain": "Explain what happened or why, without leading with apology or a new plan.",
        "acknowledge": (
            "Show you heard them and care, without new facts, an apology, or a plan. "
            "Use for light chat or when they mainly need to feel seen."
        ),
        "say_less": (
            "Keep it short or add nothing. Extra words would over-explain, reopen a closed topic, "
            "or pour fuel on an ultimatum that told you not to talk."
        ),
        "make_plan": (
            "Propose or confirm logistics (time, place, task) for a non-conflict request "
            "such as a meal or a meeting."
        ),
    },
}

SHE_NEEDS = {
    "type": "choice",
    "instructions": (
        "What does the other person need from you right now? Judge the LATEST message first. "
        "If they genuinely accepted (thanks / got it / 没事了 / 那就这样 / 收到了 / 过去了), "
        "you MUST choose nothing, even if earlier they wanted action or an apology. "
        "Sarcastic 'I'm used to it', 'whatever', 'I don't want to hear it', 'don't bother coming' "
        "is NOT genuine satisfaction - do not choose nothing. "
        "If they asked you to recap a named time/place/date, choose action. "
        "If they are testing whether you remember or still care, and the content is unnamed, choose care."
    ),
    "criteria": {
        "apology": "They need a sincere apology for hurt or a mistake, and they have not accepted one yet.",
        "action": (
            "They need a concrete action, time, commitment, recap of a named fact, or follow-through, "
            "and they have not yet accepted one."
        ),
        "explanation": "They need a clear explanation of what happened or why, and have not received it.",
        "care": (
            "They need proof you remember, listen, or care - a loyalty or attention test - "
            "not yet a plan or an apology. Sarcastic 'I am used to it' belongs here, not nothing."
        ),
        "nothing": (
            "They need nothing further. Genuine acceptance, a peaceful closed topic, "
            "warm casual chat with no ask, or a rupture where they told you not to reply. "
            "Not sarcasm pretending to be fine."
        ),
    },
}

TENSION_RESOLVED = {
    "type": "noul",
    "instructions": (
        "Has interpersonal tension already been resolved? "
        "Answer true only if there was never tension, or the other person has clearly accepted, "
        "cooled down, joked again, or said it is fine. "
        "A sarcastic 'you better', an unanswered test, leftover blame, or an open ultimatum means false."
    ),
    "criteria": {
        "true": (
            "No remaining tension: they accepted, joked again, said it's fine, "
            "confirmed a happy plan, or the chat was never tense."
        ),
        "false": (
            "Tension is still present: they are waiting, testing, angry, sarcastic, "
            "issuing an ultimatum, or the issue is open."
        ),
    },
}

RANK_INSTRUCTIONS = (
    "Which candidate reply is the most appropriate next message, "
    "given the conversation and the other person's true need? "
    "Prefer a reply that matches the best action type. "
    "Penalize dismissive, over-promising, or off-topic replies. "
    "If the facts are not yet confirmed, prefer the candidate that looks them up "
    "instead of faking memory or a vague apology."
)


def build_payload(relationship: str, messages: list[tuple[str, str]],
                  candidates: list[str]) -> dict:
    """构造与 app 发出的完全同形的请求体。"""
    if len(candidates) != 3:
        raise ValueError("排序题需要恰好 3 条候选")

    questions = {
        "literal_question": LITERAL_QUESTION,
        "true_intent": TRUE_INTENT,
        "danger_level": DANGER_LEVEL,
        "should_reply_now": SHOULD_REPLY_NOW,
        "best_action": BEST_ACTION,
        "she_needs": SHE_NEEDS,
        "tension_resolved": TENSION_RESOLVED,
        "best_reply": {
            "type": "choice",
            "instructions": RANK_INSTRUCTIONS,
            "criteria": {k: v for k, v in zip(("reply_a", "reply_b", "reply_c"), candidates)},
        },
    }
    state = {"chat": {
        "relationship": relationship,
        "messages": [{"from": who, "text": text} for who, text in messages],
        "latest_from": messages[-1][0],
    }}
    return {"model": "nanojev-local", "state": state, "questions": questions}


DEFAULT_MESSAGES = [
    ("me", "今天有点忙，晚点回你"),
    ("other", "嗯"),
    ("me", "吃饭了吗"),
    ("other", "吃了"),
    ("other", "你昨天说今天要跟我说的事，是什么来着？"),
    ("me", "啊这个……"),
    ("other", "你该不会是忘了吧"),
    ("other", "我就知道你又会这样，算了，你说吧我听着"),
]

DEFAULT_CANDIDATES = [
    "抱歉，是我不好，我不该忘的",
    "你先别生气，我这就好好跟你说清楚",
    "我在的，你说",
]


def call(url: str, payload: dict, timeout: int, token: str | None = None) -> tuple[dict, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
    except urllib.error.URLError as e:
        raise SystemExit(
            f"连不上 {url}：{e.reason}\n服务起了吗？先跑 ./run_server.sh"
        )
    return json.loads(raw), time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/alpha/decisions")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--token")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    payload = build_payload(
        "对方是我的伴侣；from=me 的是我发的，from=other 的是对方发的",
        DEFAULT_MESSAGES,
        DEFAULT_CANDIDATES,
    )

    print(f"POST {args.url}")
    print(f"题目数 = {len(payload['questions'])}（7 判断 + 1 排序）")
    print()

    for i in range(args.repeat):
        out, elapsed = call(args.url, payload, args.timeout, args.token)
        ex = out.get("execution", {})
        print(f"--- 第 {i + 1} 次 ---")
        print(f"  设备           : {ex.get('device')} / {ex.get('dtype')}")
        print(f"  候选路径数     : {ex.get('candidate_leaves')}")
        print(f"  预填 token 总数: {ex.get('total_prefill_tokens')}")
        print(f"  服务端推理耗时 : {ex.get('server_seconds', 0):.2f} s")
        print(f"  往返总耗时     : {elapsed:.2f} s")
        print("  答案：")
        for qid, ans in out.get("answers", {}).items():
            if "noul" in ans:
                print(f"    {qid:<18} noul={ans['noul']:.3f}  conf={ans.get('confidence', 0):.3f}")
            elif "score" in ans:
                print(f"    {qid:<18} score={ans['score']:.2f}  conf={ans.get('confidence', 0):.3f}  "
                      f"levels={len(ans.get('legend') or {})}")
            else:
                top = sorted((ans.get("probabilities") or {}).items(),
                             key=lambda kv: -kv[1])[:3]
                tops = ", ".join(f"{k}={v:.2f}" for k, v in top)
                print(f"    {qid:<18} choice={ans.get('choice')}  conf={ans.get('confidence', 0):.3f}  top: {tops}")
        print()


if __name__ == "__main__":
    main()

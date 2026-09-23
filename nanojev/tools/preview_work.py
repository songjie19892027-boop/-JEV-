#!/usr/bin/env python3
"""职场版判断题集的真实推理验证。

对 4 个典型职场场景各跑一次 9 道判断题（6 是非 + 1 意图 + 1 动作 + 1 风险），
打印每题的真实概率分布，并本地复现关键词规则层的命中结果。用来核对两件事：

  1. **设计前提是否成立** —— 是非题的把握度是否明显高于多选 / 评分题。
     若不成立，整套"把关键判断拆成是非题"的思路就要推翻。
  2. **方向是否正确** —— 纯知会、派活、甩锅三种场景是否被判到对的一侧，
     以及一条正常的任务安排会不会被**误报**成派活（对照组，最重要）。

题目内容与 app/src/main/java/com/jev/probe/jev/JevQuestions.kt 保持一致；
关键词表与 JevWorkRules.kt 保持一致。改任一侧都要同步这里。

用法：
    python -B tools/preview_work.py
"""
import json
import os
import urllib.request

BASE = "http://127.0.0.1:8788"
REL = "对方是我的上级领导；from=me 的是我发的，from=other 的是对方（领导或同事）发给我的"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "work_preview.json")


def noul(ins, t, f):
    return {"type": "noul", "instructions": ins, "criteria": {"true": t, "false": f}}


def choice(ins, crit):
    return {"type": "choice", "instructions": ins, "criteria": crit}


def score(ins, levels):
    return {"type": "score", "instructions": ins, "criteria": levels}


QUESTIONS = {
    "has_subtext": noul(
        "Does the other person's latest message carry meaning beyond its literal wording? "
        "Judge from the whole thread and from the speaker's position relative to you, "
        "not from one sentence in isolation. A manager often states a want indirectly, "
        "and 'what do you think' can be an instruction.",
        "There is subtext: a test of your attitude or reliability, a softened order that is still an order, "
        "a warning laid down for future accountability, criticism delivered as a question, "
        "a reminder that they know about something you did not report, or pressure they will not state outright.",
        "The message says what it means: a plain instruction, a plain status update, a plain question, "
        "or ordinary coordination, with no hidden test, warning, or unstated requirement.",
    ),
    "shifting_blame": noul(
        "Is the other person moving responsibility for an outcome onto you? "
        "Consider who actually owned the decision or the task in the first place. "
        "A question such as 'was this on your side?' can be an attempt to establish that the fault is yours. "
        "Do NOT count it when they are simply asking for facts, or when they openly own their own part.",
        "They attribute an outcome, a delay, or a mistake to you or to your side in a way that would make you "
        "the accountable one if this were reviewed later: 'you were the one following it', 'I told you before', "
        "'why didn't you raise it earlier', 'that is your area', 'you confirmed it'.",
        "They ask for facts, share context, or accept their own part. No blame is being attributed to you.",
    ),
    "shifting_work": noul(
        "Is the other person handing you work outside your remit, without naming resources, authority, or a deadline? "
        "A manager may assign work legitimately, so judge the BOUNDARY rather than the seniority: "
        "does this belong to someone else or to another team, and is it being passed to you loosely "
        "with words like 'you handle it' or 'you know this better'?",
        "Work that belongs to another person, another team, or is outside your established responsibilities "
        "is being placed with you casually - 'you just follow up on this', 'you know this area better', "
        "'while you are at it, also handle...', 'you take the lead on this' - "
        "with no named resource, authority, or deadline.",
        "This is normal work inside your remit, or they are only asking whether you could support, "
        "rather than assigning it to you.",
    ),
    "informing_only": noul(
        "Is the other person only informing you, with no action expected from you? "
        "This is the counterpart question that prevents over-reading. "
        "Answer TRUE when the message is a notification, a status update, a heads-up, or background, "
        "and they are not waiting for your response, decision, or work.",
        "Purely informational: they are notifying you of a decision, a status, or background. "
        "They are not waiting on you to reply, decide, or act.",
        "They are waiting for something from you: a reply, a decision, a plan, a confirmation, or actual work.",
    ),
    "needs_record": noul(
        "Should this exchange be confirmed in writing? "
        "Answer TRUE when the message touches responsibility boundaries, committed dates, "
        "resources or budget, cross-team interfaces, or a decision that could be reviewed later - "
        "cases where a chat-only understanding is risky for you.",
        "It carries something worth confirming in writing: a responsibility or ownership boundary, "
        "a time commitment, a resource or budget promise, a decision, "
        "or an instruction that could later be disputed.",
        "Ordinary day-to-day coordination. Nothing here would need to be restated in an email or group message.",
    ),
    "implied_deadline": noul(
        "Does the message imply a deadline or urgency without naming a clear and reasonable date? "
        "Judge the pressure, not the calendar.",
        "There is urgency or a time expectation that is either unstated or vague: 'as soon as possible', "
        "'these two days', 'today', 'do not drag it out', 'I am waiting', 'give me an answer', "
        "'arrange the timing yourself but do not let it slip'.",
        "No time pressure, or the deadline is explicit and reasonable.",
    ),
    "what_they_want": choice(
        "What does the other person mainly want from you? Judge the LATEST message first, then the thread. "
        "If they are only passing on information and need nothing from you, choose informing - "
        "do not treat every message as a task.",
        {
            "assign_work": "They want you to take on a piece of work: a task, a follow-up, or a lead role, beyond simply answering a question.",
            "shift_blame": "They want you to acknowledge that something is your responsibility or your oversight.",
            "seek_support": "They want your support - people, data, time, or coordination - for something that they own.",
            "seek_answer": "They want a plan, a number, or a substantive answer from you, not just an acknowledgement.",
            "press_speed": "They want the thing done faster, or want progress reported to them now.",
            "informing": "They want nothing further from you. This is a notification to keep you in the loop.",
        },
    ),
    "best_action": choice(
        "What type of next move is best? Choose the action type only - do not decide whether to send a message "
        "right now, and ignore timing. The other person is usually your superior, so the goal is to stay "
        "cooperative while keeping the boundary and the record clear. Never suggest refusing or pushing back hard.",
        {
            "confirm_scope": "Confirm who owns this and what your part is, framed as a question. The safest way to avoid silently absorbing work or blame.",
            "ask_details": "Ask for what is missing first - scope, deadline, resource, or the exact standard expected - before you commit to anything.",
            "restate_confirm": "Restate your understanding in writing and ask them to confirm. Creates a record without confrontation.",
            "give_plan": "Give a short plan with scope, order, and timeline, and state what you need from others.",
            "accept_normal": "Accept normally, and state when you will deliver.",
            "hold_and_watch": "Give a brief, non-committal response and watch how it develops before investing effort.",
            "private_talk": "Not suitable for text; raise it in a call or face to face.",
        },
    ),
    "risk_level": score(
        "How unfavourable is this message for you? Score the CURRENT message. "
        "A legitimate work assignment is not a risk even when it is heavy. "
        "The risk lives in the boundary: someone else's work or blame being placed on you, "
        "or an unfair record being created. "
        "If a responsibility has already been pushed onto you and not withdrawn, stay in the high bins "
        "even if the latest line sounds friendly.",
        [
            "Ordinary coordination or small talk. Nothing is asked and nothing is at stake.",
            "A routine request clearly inside your remit, with a clear scope.",
            "Normal work handoff; the boundary is clear and the workload is reasonable.",
            "Slightly vague: the scope or the deliverable is not fully specified, but nothing is being shifted onto you.",
            "The boundary is blurring. The wording leaves it unclear whose job this is, and it is worth clarifying before acting.",
            "Work or a follow-up that is not clearly yours is being placed with you, without resources or a deadline.",
            "Responsibility for an outcome is starting to be attached to you: 'you were following it', 'you did not raise it'.",
            "A blame or ownership transfer is fairly clear, and refusing directly would be awkward given the reporting line.",
            "An unfair record is being created - what you said or committed to is being restated inaccurately, or fault is being fixed on you in writing.",
            "Outright scapegoating: a known failure is being placed on you in front of others or on the record, or a threat to escalate is attached to it.",
        ],
    ),
}

BOOL_TITLE = {
    "has_subtext": "有没有话外之意？",
    "shifting_blame": "是否把责任推给你？",
    "shifting_work": "是否派了不属于你的活？",
    "informing_only": "只是知会，还是要你动？",
    "needs_record": "要不要留文字记录？",
    "implied_deadline": "有没有隐含时限？",
}
BOOL_LABELS = {
    "has_subtext": ("有，另有深意", "没有，就是字面"),
    "shifting_blame": ("在推，往你身上引", "没有，就事论事"),
    "shifting_work": ("在派，超出职责", "没有，正常安排"),
    "informing_only": ("只是知会", "在等你回应"),
    "needs_record": ("建议留痕", "不用，日常"),
    "implied_deadline": ("有，在催", "没有时间压力"),
}
# 与 JevWorkRules.kt 保持一致的词表（只用于本地复现命中，不改判定）
RULES = {
    "疑似派活": ["你看着办", "你跟一下", "你跟进", "跟进一下", "你盯一下", "盯一下",
             "你来牵头", "你牵头", "你来统筹", "你来负责", "你负责",
             "你比较熟", "你熟", "这块你", "顺便把", "顺带把", "顺便帮",
             "顺手把", "顺手帮", "顺手弄",
             "先弄起来", "你先弄", "你来弄", "你弄一下", "交给你了",
             "你来安排", "你这边安排", "你安排一下", "你处理一下", "你出面", "你协调一下"],
    "疑似推责": ["我之前不是说过了", "我不是说过", "我说过了", "我早就说过",
             "当时是你", "是你跟的", "你当时跟的", "我以为你知道", "我以为你清楚",
             "你为什么不早说", "你怎么不早说", "早点怎么不说", "你确认过的",
             "你当时确认", "你答应过", "你也有责任", "你也有份", "你跑不了",
             "这不是我的事", "不归我管", "跟我没关系", "你自己看", "你没提醒我",
             "你那边没跟上", "出了问题你负责", "出问题你负责", "你来担"],
    "暗中施压": ["我只要结果", "我不管过程", "看结果", "你自己把握", "自己想办法",
             "想想办法", "克服一下", "今天之内", "这两天", "别拖", "抓紧",
             "我等着", "要有说法", "给我个说法", "你觉得呢"],
    "像是纯知会": ["同步你一下", "同步一下", "知会你", "告知你", "告知一下",
               "不用回复", "不用管", "供参考", "留个底", "留个记录",
               "跟你说一下", "报备", "我这边已经", "已经处理好了"],
}

CASES = [
    ("① 纯知会（对照组：应当判为「不用动」）", [
        ("other", "在吗"), ("me", "在的，王总"),
        ("other", "下午那个会改到三点了，同步你一下"),
    ]),
    ("② 正常任务（对照组：不该被误报成派活）", [
        ("other", "明天上午十点开个会"), ("me", "好的"),
        ("other", "你把上个月的收费数据整理一份带过来"),
    ]),
    ("③ 派活（顺带口吻、不说资源时限）", [
        ("other", "在吗"), ("me", "在的，王总"),
        ("other", "上次说的那个报表你跟一下，我这两天要用"),
    ]),
    ("④ 甩锅（把因果反过来讲）", [
        ("other", "那个数据我当时不是跟你说过了吗"),
        ("me", "我以为那个是李工那边出的"),
        ("other", "这块一直是你在跟的，出了问题你负责"),
    ]),
]


def scan_rules(text):
    """与 JevWorkRules.scan() 保持一致：短语存在包含关系时只保留长的那条。

    例：「出了问题你负责」同时命中推责（长词条）与派活（「你负责」），
    后者是前者的子串，语境已被长词条覆盖，两条都报会看不出重点。
    同一短语命中多个类别不去重（有意保留）。
    """
    pairs = [(kind, p) for kind, phrases in RULES.items()
             for p in phrases if p in text]
    kept = [(k, p) for k, p in pairs
            if not any(o != p and p in o for _, o in pairs)]
    out = {}
    for kind, p in kept:
        out.setdefault(kind, []).append(p)
    return out


def ask(messages):
    body = {
        "model": "typesafe/jev-1.13",
        "state": {"chat": {
            "relationship": REL,
            "messages": [{"from": s, "text": t} for s, t in messages],
            "latest_from": messages[-1][0],
        }},
        "questions": QUESTIONS,
    }
    req = urllib.request.Request(
        BASE + "/api/alpha/decisions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read().decode("utf-8"))["answers"]


def show(name, messages, answers):
    last = messages[-1][1]
    print("\n" + "=" * 74)
    print(f"场景：{name}")
    print(f"对方最后一条：{last}")
    hits = scan_rules(last)
    print("关键词命中：" + ("；".join(f"{k} → {' · '.join(v)}" for k, v in hits.items()) if hits else "（无）"))

    print("\n【是非题 · 模型最擅长，两行都列，按概率降序】")
    for qid, (tl, fl) in BOOL_LABELS.items():
        a = answers.get(qid) or {}
        p = a.get("noul")
        if p is None:
            continue
        rows = sorted([(tl, p * 100), (fl, (1 - p) * 100)], key=lambda x: -x[1])
        mark = "◆" if rows[0][1] >= 60 else "·"
        print(f" {mark} {BOOL_TITLE[qid]:<22} {rows[0][0]} {rows[0][1]:5.1f}%   "
              f"{rows[1][0]} {rows[1][1]:5.1f}%")

    print("\n【多选 / 评分 · 仅参考，括号内是该题型的随机基线】")
    for qid, ttl, base in (("what_they_want", "对方想要什么", 100 / 6), ("best_action", "最佳应对", 100 / 7)):
        a = answers.get(qid) or {}
        probs = a.get("probabilities") or {}
        if not probs:
            continue
        top = max(probs.items(), key=lambda kv: kv[1])
        print(f"    {ttl}：{top[0]} {top[1] * 100:.1f}%   (随机 {base:.1f}%)")
    a = answers.get("risk_level") or {}
    probs = a.get("probabilities") or {}
    if a:
        top = max(probs.values()) if probs else 0.0
        print(f"    风险等级：{a.get('score', 0):.2f} / 10   (最高档把握 {top * 100:.1f}%，随机 10.0%)")


def main():
    print("职场版判断题集 · 真实推理验证")
    print(f"后端：{BASE}　题目数：{len(QUESTIONS)}")
    results = {}
    for name, msgs in CASES:
        print(f"\n→ 推理中：{name} …", flush=True)
        try:
            ans = ask(msgs)
        except Exception as e:  # noqa: BLE001
            print(f"  失败：{e}")
            continue
        show(name, msgs, ans)
        results[name] = {
            "messages": msgs,
            "hits": scan_rules(msgs[-1][1]),
            "answers": ans,
        }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"\n明细已写入 {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()

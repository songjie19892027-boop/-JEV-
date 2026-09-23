package com.jev.probe.jev

import com.jev.probe.core.ChatSnapshot
import org.json.JSONArray
import org.json.JSONObject

/**
 * 职场版判断题集。
 *
 * 为什么这样设计（2026-09-23 实测依据）
 * -----------------------------------
 * 本地 NanoJev 底座是 Qwen3-0.6B，用**游戏对局**训练，中国职场话术对它是陌生领域。
 * 实测结论：
 *   - 是非题判断力 80% 以上（如「是不是字面意思」83%、「该不该给实质」85%）
 *   - 多选 / 评分题只有 20% 上下，接近随机猜（6 选 1 均匀 = 16.7%）
 *
 * 因此本版把最要紧的四个判断（有没有深意 / 是否推责 / 是否派活 / 该不该留痕）
 * **全部拆成独立的是非题**，而不是塞进一道多选题让模型在里面挑 —— 后者正好
 * 落在它最弱的形式上。多选与评分降级为「辅助参考」，UI 上会明确标注。
 *
 * 视角与方向约定
 * ------------
 * - from=other 是对方（默认上级）发的，from=me 是我发的。
 * - **所有是非题的 true 一律表示「是 / 有问题 / 需要留意」**，false 表示「没事」。
 *   这样 p_true 直接就是「需要警惕」的概率，UI 不需要做语义反转，也不会看反。
 * - instructions 用英文（沿用模型训练口径），聊天原文保持中文。
 * - 题目里刻意加了 [informing_only] 这道反向题：0.6B 模型容易「看什么都有深意」，
 *   给它一个「这只是通知，不用动」的出口，能压住大量误报。
 */
object JevQuestions {

    private fun noul(instructions: String, t: String, f: String) = JSONObject().apply {
        put("type", "noul")
        put("instructions", instructions)
        // 顺序固定 true 在前：服务端 p_true = probabilities[1]，与这里的顺序绑定。
        put("criteria", JSONObject().put("true", t).put("false", f))
    }

    private fun choice(instructions: String, criteria: Map<String, String>) = JSONObject().apply {
        put("type", "choice")
        put("instructions", instructions)
        put("criteria", JSONObject().also { c -> criteria.forEach { (k, v) -> c.put(k, v) } })
    }

    private fun score(instructions: String, levels: List<String>) = JSONObject().apply {
        put("type", "score")
        put("instructions", instructions)
        put("criteria", JSONArray().also { a -> levels.forEach { a.put(it) } })
    }

    /** 9 道判断题（6 是非 + 1 意图 + 1 动作 + 1 风险）。每次调用返回全新对象。 */
    fun judge(): JSONObject = JSONObject().apply {

        put("has_subtext", noul(
            "Does the other person's latest message carry meaning beyond its literal wording? " +
                "Judge from the whole thread and from the speaker's position relative to you, " +
                "not from one sentence in isolation. A manager often states a want indirectly, " +
                "and 'what do you think' can be an instruction.",
            "There is subtext: a test of your attitude or reliability, a softened order that is still an order, " +
                "a warning laid down for future accountability, criticism delivered as a question, " +
                "a reminder that they know about something you did not report, or pressure they will not state outright.",
            "The message says what it means: a plain instruction, a plain status update, a plain question, " +
                "or ordinary coordination, with no hidden test, warning, or unstated requirement."
        ))

        put("shifting_blame", noul(
            "Is the other person moving responsibility for an outcome onto you? " +
                "Consider who actually owned the decision or the task in the first place. " +
                "A question such as 'was this on your side?' can be an attempt to establish that the fault is yours. " +
                "Do NOT count it when they are simply asking for facts, or when they openly own their own part.",
            "They attribute an outcome, a delay, or a mistake to you or to your side in a way that would make you " +
                "the accountable one if this were reviewed later: 'you were the one following it', 'I told you before', " +
                "'why didn't you raise it earlier', 'that is your area', 'you confirmed it'.",
            "They ask for facts, share context, or accept their own part. No blame is being attributed to you."
        ))

        put("shifting_work", noul(
            "Is the other person handing you work outside your remit, without naming resources, authority, or a deadline? " +
                "A manager may assign work legitimately, so judge the BOUNDARY rather than the seniority: " +
                "does this belong to someone else or to another team, and is it being passed to you loosely " +
                "with words like 'you handle it' or 'you know this better'?",
            "Work that belongs to another person, another team, or is outside your established responsibilities " +
                "is being placed with you casually - 'you just follow up on this', 'you know this area better', " +
                "'while you are at it, also handle...', 'you take the lead on this' - " +
                "with no named resource, authority, or deadline.",
            "This is normal work inside your remit, or they are only asking whether you could support, " +
                "rather than assigning it to you."
        ))

        put("informing_only", noul(
            "Is the other person only informing you, with no action expected from you? " +
                "This is the counterpart question that prevents over-reading. " +
                "Answer TRUE when the message is a notification, a status update, a heads-up, or background, " +
                "and they are not waiting for your response, decision, or work.",
            "Purely informational: they are notifying you of a decision, a status, or background. " +
                "They are not waiting on you to reply, decide, or act.",
            "They are waiting for something from you: a reply, a decision, a plan, a confirmation, or actual work."
        ))

        put("needs_record", noul(
            "Should this exchange be confirmed in writing? " +
                "Answer TRUE when the message touches responsibility boundaries, committed dates, " +
                "resources or budget, cross-team interfaces, or a decision that could be reviewed later - " +
                "cases where a chat-only understanding is risky for you.",
            "It carries something worth confirming in writing: a responsibility or ownership boundary, " +
                "a time commitment, a resource or budget promise, a decision, " +
                "or an instruction that could later be disputed.",
            "Ordinary day-to-day coordination. Nothing here would need to be restated in an email or group message."
        ))

        put("implied_deadline", noul(
            "Does the message imply a deadline or urgency without naming a clear and reasonable date? " +
                "Judge the pressure, not the calendar.",
            "There is urgency or a time expectation that is either unstated or vague: 'as soon as possible', " +
                "'these two days', 'today', 'do not drag it out', 'I am waiting', 'give me an answer', " +
                "'arrange the timing yourself but do not let it slip'.",
            "No time pressure, or the deadline is explicit and reasonable."
        ))

        put("what_they_want", choice(
            "What does the other person mainly want from you? Judge the LATEST message first, then the thread. " +
                "If they are only passing on information and need nothing from you, choose informing - " +
                "do not treat every message as a task.",
            linkedMapOf(
                "assign_work" to ("They want you to take on a piece of work: a task, a follow-up, " +
                    "or a lead role, beyond simply answering a question."),
                "shift_blame" to ("They want you to acknowledge that something is your responsibility " +
                    "or your oversight."),
                "seek_support" to ("They want your support - people, data, time, or coordination - " +
                    "for something that they own."),
                "seek_answer" to ("They want a plan, a number, or a substantive answer from you, " +
                    "not just an acknowledgement."),
                "press_speed" to ("They want the thing done faster, or want progress reported to them now."),
                "informing" to ("They want nothing further from you. This is a notification to keep you in the loop.")
            )
        ))

        put("best_action", choice(
            "What type of next move is best? Choose the action type only - do not decide whether to send a message " +
                "right now, and ignore timing. The other person is usually your superior, so the goal is to stay " +
                "cooperative while keeping the boundary and the record clear. Never suggest refusing or pushing back hard.",
            linkedMapOf(
                "confirm_scope" to ("Confirm who owns this and what your part is, framed as a question. " +
                    "The safest way to avoid silently absorbing work or blame."),
                "ask_details" to ("Ask for what is missing first - scope, deadline, resource, or the exact standard " +
                    "expected - before you commit to anything."),
                "restate_confirm" to ("Restate your understanding in writing and ask them to confirm. " +
                    "Creates a record without confrontation."),
                "give_plan" to ("Give a short plan with scope, order, and timeline, and state what you need from others."),
                "accept_normal" to "Accept normally, and state when you will deliver.",
                "hold_and_watch" to ("Give a brief, non-committal response and watch how it develops " +
                    "before investing effort."),
                "private_talk" to "Not suitable for text; raise it in a call or face to face."
            )
        ))

        put("risk_level", score(
            "How unfavourable is this message for you? Score the CURRENT message. " +
                "A legitimate work assignment is not a risk even when it is heavy. " +
                "The risk lives in the boundary: someone else's work or blame being placed on you, " +
                "or an unfair record being created. " +
                "If a responsibility has already been pushed onto you and not withdrawn, stay in the high bins " +
                "even if the latest line sounds friendly.",
            listOf(
                "Ordinary coordination or small talk. Nothing is asked and nothing is at stake.",
                "A routine request clearly inside your remit, with a clear scope.",
                "Normal work handoff; the boundary is clear and the workload is reasonable.",
                "Slightly vague: the scope or the deliverable is not fully specified, but nothing is being shifted onto you.",
                "The boundary is blurring. The wording leaves it unclear whose job this is, and it is worth clarifying before acting.",
                "Work or a follow-up that is not clearly yours is being placed with you, without resources or a deadline.",
                "Responsibility for an outcome is starting to be attached to you: 'you were following it', 'you did not raise it'.",
                "A blame or ownership transfer is fairly clear, and refusing directly would be awkward given the reporting line.",
                "An unfair record is being created - what you said or committed to is being restated inaccurately, " +
                    "or fault is being fixed on you in writing.",
                "Outright scapegoating: a known failure is being placed on you in front of others or on the record, " +
                    "or a threat to escalate is attached to it."
            )
        ))
    }

    /** 从快照构造 Jev state（最近 10 条）。 */
    fun buildState(snapshot: ChatSnapshot, relationship: String): JSONObject {
        val msgs = JSONArray()
        val last10 = snapshot.messages.takeLast(10)
        for (m in last10) {
            msgs.put(JSONObject().put("from", m.side).put("text", m.text))
        }
        val chat = JSONObject()
            .put("relationship", relationship)
            .put("messages", msgs)
            .put("latest_from", last10.lastOrNull()?.side ?: "other")
        return JSONObject().put("chat", chat)
    }

    /** 三条候选回复的排序题（中文原文保留）。 */
    fun rankQuestion(candidates: List<String>): JSONObject {
        require(candidates.size == 3) { "rankQuestion expects exactly 3 candidates" }
        val keys = listOf("reply_a", "reply_b", "reply_c")
        val criteria = JSONObject()
        keys.forEachIndexed { i, k -> criteria.put(k, candidates[i]) }
        val q = JSONObject().apply {
            put("type", "choice")
            put("instructions",
                "Which candidate reply is the most appropriate next message, given the conversation, " +
                    "the other person's expectation, and the boundary between your responsibility and theirs? " +
                    "Prefer a reply that matches the best action type. " +
                    "Penalise replies that accept blame not yet established, that commit to work or dates " +
                    "outside your remit, that promise resources you do not control, " +
                    "that refuse too bluntly for a superior, or that are simply off-topic. " +
                    "If responsibility is still unclear, prefer the candidate that clarifies ownership " +
                    "or confirms in writing rather than the one that quietly takes it on.")
            put("criteria", criteria)
        }
        return JSONObject().put("best_reply", q)
    }
}

package com.jev.probe.jev

/**
 * 把 Jev 的英文 criteria key 翻译成中文短标签，并**固定展示顺序**。
 *
 * 为什么必须有这一层
 * ------------------
 * 1. 模型的原生输出是 `confirm_scope` / `shift_blame` 这类英文 key，
 *    直接显示给用户不可读。
 * 2. `probabilities` 在 JSON 里是对象，**键的迭代顺序不保证**。要让面板
 *    每次以相同的次序展示（「先确认归口与边界」永远在第一行），必须用这里
 *    定义的 ordered map 去取值，而不是遍历返回的 map。
 *
 * 是非题的文案约定
 * --------------
 * TRUE 一律表示「是 / 有问题 / 需要留意」，FALSE 表示「没事」——
 * 与服务端 p_true 的方向严格一致，UI 不做语义反转，避免看反。
 *
 * 顺序与 `JevQuestions.kt` 里 criteria 的声明顺序一一对应 —— 改一侧必须同步另一侧。
 */
object JevLabels {

    // ---------------------------------------------------------------- 是非题

    /** 话外之意。 */
    const val SUBTEXT_Q = "有没有话外之意？"
    const val SUBTEXT_TRUE = "有，另有深意"
    const val SUBTEXT_FALSE = "没有，就是字面意思"

    /** 推卸责任。 */
    const val BLAME_Q = "是否把责任推给你？"
    const val BLAME_TRUE = "在推，往你身上引"
    const val BLAME_FALSE = "没有，就事论事"

    /** 派活。 */
    const val WORK_Q = "是否派了本不属于你的活？"
    const val WORK_TRUE = "在派，超出你的职责"
    const val WORK_FALSE = "没有，属正常工作安排"

    /** 只是知会（反向校验，压住过度解读）。 */
    const val INFORM_Q = "只是知会，还是要你动？"
    const val INFORM_TRUE = "只是知会"
    const val INFORM_FALSE = "不是，在等你回应"

    /** 留痕建议。 */
    const val RECORD_Q = "要不要留文字记录？"
    const val RECORD_TRUE = "建议留痕"
    const val RECORD_FALSE = "不用，日常协作"

    /** 隐含时限。 */
    const val DEADLINE_Q = "有没有隐含时限或催办？"
    const val DEADLINE_TRUE = "有，在催"
    const val DEADLINE_FALSE = "没有时间压力"

    // ------------------------------------------------------------ 多选与评分

    /** 对方想要什么（choice，6 选项）。 */
    const val WANT_Q = "对方想要什么"
    val WANT: Map<String, String> = linkedMapOf(
        "assign_work" to "要你接一件活",
        "shift_blame" to "要你认下责任",
        "seek_support" to "要你配合支持",
        "seek_answer" to "要你给方案或数据",
        "press_speed" to "要你加快进度",
        "informing" to "只是知会，不用动"
    )

    /** 最佳应对（choice，7 选项）。 */
    const val ACTION_Q = "最佳应对"
    val ACTION: Map<String, String> = linkedMapOf(
        "confirm_scope" to "先确认归口与边界",
        "ask_details" to "先问清要求再答复",
        "restate_confirm" to "复述一遍请对方确认",
        "give_plan" to "给出方案与排期",
        "accept_normal" to "正常接下并明确时间",
        "hold_and_watch" to "先应下，观察动向",
        "private_talk" to "改线下当面沟通"
    )

    /** 风险等级（score）。 */
    const val RISK_Q = "风险等级"

    /** 安全取标签：未知 key 原样显示，便于发现模型新增了选项。 */
    fun label(map: Map<String, String>, key: String?): String =
        if (key.isNullOrBlank()) "" else map[key] ?: key
}

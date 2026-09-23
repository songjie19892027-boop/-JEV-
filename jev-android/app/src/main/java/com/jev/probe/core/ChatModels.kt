package com.jev.probe.core

import com.jev.probe.jev.JevWorkRules

/** One captured chat bubble. side is "me" (right) or "other" (left). */
data class Msg(val side: String, val text: String)

/** A snapshot of the currently-open conversation in whichever chat app is
 *  foreground (see ChatAppAdapter). */
data class ChatSnapshot(
    val title: String?,
    val messages: List<Msg>
) {
    val latestFrom: String? get() = messages.lastOrNull()?.side

    /** A stable signature of the last few messages, to detect real changes. */
    fun signature(): String =
        messages.takeLast(6).joinToString("|") { "${it.side}:${it.text}" }
}

/**
 * 一次分析的全部结果。
 *
 * 字段分三组：
 *   1. 6 道是非题（模型判断力最强的部分，也是本工具的主信号）；
 *      每个 Double 都是 **p_true = 「是」的概率**，与 JevLabels 的 _TRUE 文案对应。
 *   2. 3 道辅助题（多选 / 评分）—— 实测只有 20% 上下的判断力，UI 会标注「仅参考」。
 *   3. [ruleHits] 关键词规则层的命中，**不来自模型**，置信度高且可解释。
 */
data class Analysis(
    // 是非题：p_true 高 = 需要留意
    val hasSubtext: Double?,        // 有深意
    val shiftingBlame: Double?,     // 在推责
    val shiftingWork: Double?,      // 在派活
    val informingOnly: Double?,     // 只是知会
    val needsRecord: Double?,       // 该留痕
    val impliedDeadline: Double?,   // 有隐含时限

    // 辅助题
    val whatTheyWant: Choice?,
    val bestAction: Choice?,
    val riskLevel: Score?,

    val rankedReplies: List<RankedReply>,
    val latencyMs: Long,
    val error: String? = null,
    /** 关键词规则命中；默认为空，由调用方注入。 */
    val ruleHits: List<JevWorkRules.Hit> = emptyList()
)

data class Choice(val choice: String, val confidence: Double, val probabilities: Map<String, Double>)
data class Score(val score: Double, val confidence: Double, val maxLevel: Int)
data class RankedReply(val text: String, val prob: Double)

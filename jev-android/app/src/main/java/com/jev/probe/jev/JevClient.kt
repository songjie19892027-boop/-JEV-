package com.jev.probe.jev

import android.util.Log
import com.jev.probe.core.Analysis
import com.jev.probe.core.ChatSnapshot
import com.jev.probe.core.Choice
import com.jev.probe.core.RankedReply
import com.jev.probe.core.Score
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * 判断 + 起草候选回复。
 *
 * 判断后端有三条路，优先级与 [com.jev.probe.core.Prefs] 保持一致：
 *
 *   1. **DeepSeek 云端（[deepseekKey] 非空）—— 当前唯一可用的判断源。**
 *      把 9 道职场判断题压成一段 prompt 交给 deepseek-chat，要求它只回 JSON。
 *      云端大模型能读懂中国职场话术，这正是本地小模型做不到的事。
 *
 *   2. 本地 NanoJev（[localJevBase] 非空）—— 保留代码但**实测判断无效**：
 *      2026-09-23 的 state 敏感性对照实验显示，本地 Qwen3-0.6B 的输出与输入对话
 *      无关（5 组逻辑相反的对话，p_true 极差仅 1.8 个百分点）。走这条路的
 *      `decisions` 协议（questions JSON）仍然是完整的，将来换更大底座可直接复用。
 *
 *   3. OpenRouter（兜底）—— 原伴侣模型协议，已停用。
 *
 * **起草候选回复**跟随判断后端走（见 [draftAndRank]）：
 *   - DeepSeek：**一次调用**同时产出 3 条候选文本与各自推荐度（[draftViaDeepSeek]），
 *     不需要第二次请求。这是默认路径，也意味着**只要一个 DeepSeek 密钥就全通**。
 *   - 本地 / OpenRouter：保持原两段式（生成文本 → questions 协议排序），
 *     仅作备用保留。OpenRouter 在国内需代理，实际不可用。
 *
 * 所有密钥都是逐次传入，**从不写进日志**。
 */
class JevClient(
    private val openRouterKey: String,
    private val replyModel: String,
    private val localJevBase: String = "",
    private val deepseekKey: String = "",
    private val deepseekModel: String = "deepseek-chat",
) {

    /** 判断用的后端。顺序必须与 [Prefs.judgeBackendLabel] 一致。 */
    enum class Backend { DEEPSEEK, LOCAL, OPENROUTER }

    val judgeBackend: Backend = when {
        deepseekKey.isNotBlank() -> Backend.DEEPSEEK
        localJevBase.isNotBlank() -> Backend.LOCAL
        else -> Backend.OPENROUTER
    }

    val usingLocalJev: Boolean get() = judgeBackend == Backend.LOCAL
    val usingDeepSeek: Boolean get() = judgeBackend == Backend.DEEPSEEK

    /** 供界面显示。 */
    val backendName: String
        get() = when (judgeBackend) {
            Backend.DEEPSEEK -> "DeepSeek 云端"
            Backend.LOCAL -> "本地 NanoJev"
            Backend.OPENROUTER -> "OpenRouter 云端"
        }

    private val decisionsUrl: String =
        if (judgeBackend == Backend.LOCAL) "$localJevBase/api/alpha/decisions"
        else "https://openrouter.ai/api/alpha/decisions"
    private val chatUrl = "https://openrouter.ai/api/v1/chat/completions"
    private val deepseekUrl = "https://api.deepseek.com/chat/completions"

    // ------------------------------------------------------------------ 判断

    /** 9 道判断题。云端约 3–8 秒；本地约 1–7 秒（但结论不可信）。 */
    fun judge(snapshot: ChatSnapshot, relationship: String): Analysis {
        val start = System.currentTimeMillis()
        // 关键词规则层：只扫**对方最新那条**。不依赖任何模型，命中即高置信。
        val ruleHits = JevWorkRules.scan(
            snapshot.messages.lastOrNull { it.side == "other" }?.text ?: "")
        return try {
            when (judgeBackend) {
                Backend.DEEPSEEK -> judgeDeepSeek(snapshot, relationship, ruleHits, start)
                else -> judgeViaQuestions(snapshot, relationship, ruleHits, start)
            }
        } catch (e: Exception) {
            Log.w(TAG, "judge failed: ${e.message}")
            emptyAnalysis(start, readableError(e), ruleHits)
        }
    }

    /**
     * DeepSeek 路径：把 9 道题写进一段中文 prompt，要求模型只回 JSON。
     *
     * 为什么用 `response_format = json_object` + 低温：判断任务要的是可复现的结论，
     * 不是文采。JSON 模式还能免掉"模型在 JSON 外面裹一段解释"的经典麻烦。
     */
    private fun judgeDeepSeek(
        snapshot: ChatSnapshot,
        relationship: String,
        ruleHits: List<JevWorkRules.Hit>,
        start: Long,
    ): Analysis {
        val body = JSONObject()
            .put("model", deepseekModel)
            .put("temperature", 0.2)
            .put("response_format", JSONObject().put("type", "json_object"))
            .put("messages", JSONArray()
                .put(JSONObject().put("role", "system").put("content", JUDGE_SYSTEM))
                .put(JSONObject().put("role", "user")
                    .put("content", buildJudgePrompt(snapshot, relationship))))
        val resp = postJson(deepseekUrl, body, deepseekKey, CLOUD_READ_TIMEOUT_MS,
            headers = mapOf("HTTP-Referer" to "https://jev-assistant.local"))
        val content = resp.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optString("content") ?: ""
        if (content.isBlank()) throw RuntimeException("DeepSeek 返回空内容")
        val o = JSONObject(content)
        return Analysis(
            hasSubtext = cloudProb(o, "has_subtext"),
            shiftingBlame = cloudProb(o, "shifting_blame"),
            shiftingWork = cloudProb(o, "shifting_work"),
            informingOnly = cloudProb(o, "informing_only"),
            needsRecord = cloudProb(o, "needs_record"),
            impliedDeadline = cloudProb(o, "implied_deadline"),
            whatTheyWant = cloudChoice(o, "what_they_want"),
            bestAction = cloudChoice(o, "best_action"),
            riskLevel = cloudScore(o, "risk_level"),
            rankedReplies = emptyList(),
            latencyMs = System.currentTimeMillis() - start,
            ruleHits = ruleHits
        )
    }

    /** 本地 NanoJev / OpenRouter 路径：questions JSON 协议（保留给大底座复用）。 */
    private fun judgeViaQuestions(
        snapshot: ChatSnapshot,
        relationship: String,
        ruleHits: List<JevWorkRules.Hit>,
        start: Long,
    ): Analysis {
        if (usingLocalJev) ensureLocalReachable()
        val body = JSONObject()
            .put("model", "typesafe/jev-1.13")
            .put("state", JevQuestions.buildState(snapshot, relationship))
            .put("questions", JevQuestions.judge())
        val answers = postJson(decisionsUrl, body, openRouterKey,
            if (usingLocalJev) LOCAL_READ_TIMEOUT_MS else 25_000).optJSONObject("answers")
            ?: JSONObject()
        return Analysis(
            hasSubtext = pTrue(answers, "has_subtext"),
            shiftingBlame = pTrue(answers, "shifting_blame"),
            shiftingWork = pTrue(answers, "shifting_work"),
            informingOnly = pTrue(answers, "informing_only"),
            needsRecord = pTrue(answers, "needs_record"),
            impliedDeadline = pTrue(answers, "implied_deadline"),
            whatTheyWant = parseChoice(answers.optJSONObject("what_they_want")),
            bestAction = parseChoice(answers.optJSONObject("best_action")),
            riskLevel = parseScore(answers.optJSONObject("risk_level")),
            rankedReplies = emptyList(),
            latencyMs = System.currentTimeMillis() - start,
            ruleHits = ruleHits
        )
    }

    /**
     * 起草 3 条候选回复并排序。
     *
     * DeepSeek 路径一次调用拿全（文本 + 推荐度）；其余路径保持"先生成、再排序"两段式。
     * 这样做的直接好处：**用户只需要一个 DeepSeek 密钥**，不必再备一份 OpenRouter。
     */
    fun draftAndRank(snapshot: ChatSnapshot, relationship: String): List<RankedReply> {
        if (usingDeepSeek) return draftViaDeepSeek(snapshot, relationship)
        val candidates = generateCandidates(snapshot, relationship)
        val questions = JSONObject().put("best_reply",
            JevQuestions.rankQuestion(candidates).getJSONObject("best_reply"))
        val body = JSONObject()
            .put("model", "typesafe/jev-1.13")
            .put("state", JevQuestions.buildState(snapshot, relationship))
            .put("questions", questions)
        val url = if (usingLocalJev) decisionsUrl else "https://openrouter.ai/api/alpha/decisions"
        val answers = postJson(url, body, openRouterKey,
            if (usingLocalJev) LOCAL_READ_TIMEOUT_MS else 25_000).optJSONObject("answers")
            ?: JSONObject()
        return parseRanked(answers.optJSONObject("best_reply"), candidates)
    }

    /** 设置页连通测试用：判断 + 候选回复，顺序执行。 */
    fun analyze(snapshot: ChatSnapshot, relationship: String): Analysis {
        val a = judge(snapshot, relationship)
        if (a.error != null) return a
        val ranked = try { draftAndRank(snapshot, relationship) } catch (e: Exception) { emptyList() }
        return a.copy(rankedReplies = ranked)
    }

    // ------------------------------------------------------- Prompt 与解析

    /**
     * 判断用的 system prompt。刻意极短 —— 所有判据都放在 user 消息里，
     * 这样 system 只负责"只回 JSON"这一条约束。
     */
    private val JUDGE_SYSTEM =
        "你是职场沟通分析助手，服务对象是普通员工。你只输出一个 JSON 对象，" +
            "不要写任何解释，不要加代码块标记，不要输出 JSON 之外的任何字符。"

    /**
     * 把 9 道判断题写成中文 prompt。
     *
     * 与 [JevQuestions] 的英文版是同一套判据 —— 那边是给本地小模型/伴侣模型用的
     * questions JSON 协议，这边是给云端大模型用的一段式 prompt。**改判据必须两边同步。**
     */
    private fun buildJudgePrompt(snapshot: ChatSnapshot, relationship: String): String {
        val convo = snapshot.messages.takeLast(10).joinToString("\n") {
            (if (it.side == "me") "我" else "对方") + "：" + it.text
        }
        return """
请分析下面这段工作对话，判断对方**最新那条**消息的真实意图。

【对话背景】$relationship
【最近对话】
$convo

【第一组 · 是非判断】下列每题给出「是」的概率（0 到 1 的小数）：
- has_subtext：对方最新消息在字面之外另有含义 —— 试探你的态度、委婉施压、为以后追责留话、把批评包装成问句、暗示某个不成文的要求？
- shifting_blame：对方在把某个结果、延误或过错的责任往你身上引（例："这块一直是你在跟的""我之前不是说过了""你为什么不早说"）？
  注意：对方只是向你核实事实、或他自己先认下了他那部分，不算。
- shifting_work：对方把不属于你职责范围、或本该由别人/别的团队承接的活，用顺带、帮忙、"你比较熟"之类的口吻交给你，且没有明确资源、授权或期限？
  注意：上级给自己团队正常派活不算 —— 本题判断的是"这是不是你的活"，不是"他是不是你领导"。
- informing_only：对方只是知会你，并没有等你回应、决策或动手？
- needs_record：这段内容涉及责任划分、时间承诺、资源支持或跨部门界面，值得用邮件或文字复述确认一遍？
- implied_deadline：对方在催进度，但**没给出明确日期**（如"尽快""这两天""我等着""你自己把握"）？
  注意：若对方已经给了明确时间（如"周五前""下周三"），本题应为低 —— 那是正常排期，不算隐含压力。

【第二组 · 选择】给出每一项的概率（组内总和为 1）：
- what_they_want：对方主要想要什么？
  assign_work=要你接一件活 / shift_blame=要你认下责任 / seek_support=要你配合支持 /
  seek_answer=要你给方案或数据 / press_speed=要你加快进度 / informing=只是知会·不用动
- best_action：最合适的应对动作？注意对方通常是你的上级，**不能硬顶、不能直接拒绝**。
  confirm_scope=先确认归口与边界（不接受也不拒绝，先把"这是谁的活"问清） /
  ask_details=先问清要求再答复 / restate_confirm=复述一遍请对方确认（留痕） /
  give_plan=给出方案与排期 / accept_normal=正常接下并明确交付时间 /
  hold_and_watch=先应下、观察动向 / private_talk=不适合文字说，改线下当面

【第三组 · 评分】
- risk_level：这条消息对你的不利程度，取 0 到 9 的整数。
  0=正常协调无风险；3=分寸略含糊但没往你身上推；
  6=明显在把不属于你的工作或责任按给你；9=公然甩锅或已在书面留证。

【输出格式】只输出下面这个 JSON，字段齐全，不要任何其它文字：
{"has_subtext":0.0,"shifting_blame":0.0,"shifting_work":0.0,"informing_only":0.0,
"needs_record":0.0,"implied_deadline":0.0,
"what_they_want":{"assign_work":0.0,"shift_blame":0.0,"seek_support":0.0,"seek_answer":0.0,"press_speed":0.0,"informing":0.0},
"best_action":{"confirm_scope":0.0,"ask_details":0.0,"restate_confirm":0.0,"give_plan":0.0,"accept_normal":0.0,"hold_and_watch":0.0,"private_talk":0.0},
"risk_level":0}
""".trimIndent()
    }

    private fun cloudProb(o: JSONObject, key: String): Double? {
        if (!o.has(key)) return null
        val v = o.optDouble(key, Double.NaN)
        return if (v.isNaN()) null else v.coerceIn(0.0, 1.0)
    }

    private fun cloudChoice(o: JSONObject, key: String): Choice? {
        val p = o.optJSONObject(key) ?: return null
        val probs = HashMap<String, Double>()
        p.keys().forEach { k -> probs[k] = p.optDouble(k, 0.0).coerceAtLeast(0.0) }
        if (probs.isEmpty()) return null
        val best = probs.maxByOrNull { it.value }?.key ?: return null
        return Choice(best, probs[best] ?: 0.0, probs)
    }

    private fun cloudScore(o: JSONObject, key: String): Score? {
        if (!o.has(key)) return null
        val lvl = o.optInt(key, -1)
        if (lvl !in 0..9) return null
        // 云端给的是单值，没有档位分布；confidence 记 1.0 表示"无需提示把握度"。
        return Score(lvl.toDouble(), 1.0, 9)
    }

    // ------------------------------------------------------------- 候选回复

    /** 起草用的 system prompt。与判据 prompt 一样，只负责"只回 JSON"这一条约束。 */
    private val DRAFT_SYSTEM =
        "你是中文职场沟通助手，服务对象是普通员工，对方通常是用户的上级或同事。" +
            "你只输出一个 JSON 对象，不要写任何解释，不要加代码块标记。"

    /**
     * 候选回复的写作要求。**三条策略必须不同**，这是核心 —— 三条意思差不多的回复
     * 没有选择价值。措辞上守两条边界：不硬顶、不认领未确认的责任。
     */
    private val DRAFT_RULES = """
【写法要求】给出 3 条可直接发送的回复，三条策略必须明显不同：
1. 稳妥接住：明确自己交付什么、什么时候给（不推诿，但也不扩大范围）；
2. 请教口吻确认归口：用问句把"这是谁的活、需要什么资源"问清楚，不直接拒绝；
3. 简短回应：先给一个不承诺具体范围的回复，为后续确认留出空间。
【硬约束】对方通常是上级，不能硬顶、不能直接拒绝、不能空泛表态；
不要承诺职责范围之外的事，不要认领尚未确认的责任；每条不超过 50 字；
口吻专业克制、不卑不亢，符合中国企业即时通讯习惯。

【fit 怎么给】0 到 1 的小数，表示这条回复在本场景下的推荐程度（越高越推荐）。
三条之间要拉开差距，不要都给 0.8 这种含糊值。
""".trimIndent()

    /**
     * DeepSeek 起草：一次调用同时拿到 3 条候选文本与各自推荐度。
     *
     * 为什么不让模型自己排序、两段式：云端大模型在生成时就已经知道哪条更合适，
     * 让它顺手给个 fit 比"生成完再发一次请求让别的模型排序"更省一次往返，也少一个
     * 需要用户单独申请密钥的依赖。
     */
    private fun draftViaDeepSeek(snapshot: ChatSnapshot, relationship: String): List<RankedReply> {
        val convo = snapshot.messages.takeLast(10).joinToString("\n") {
            (if (it.side == "me") "我" else "对方") + "：" + it.text
        }
        val user = """
请以「我」的身份，回复下面这段工作对话里对方的**最新那条**消息。

【我的角色】$relationship
【最近对话】
$convo

$DRAFT_RULES
【输出格式】只输出下面这个 JSON，不要任何其它文字：
{"replies":[{"text":"回复正文","fit":0.0,"why":"一句话说明这条的策略"}]}
""".trimIndent()
        val messages = JSONArray()
            .put(JSONObject().put("role", "system").put("content", DRAFT_SYSTEM))
            .put(JSONObject().put("role", "user").put("content", user))
        val body = JSONObject()
            .put("model", deepseekModel)
            .put("messages", messages)
            // 起草要一点多样性（三条得拉开），但也不能飘；0.6 是实测比较稳的档。
            .put("temperature", 0.6)
            .put("response_format", JSONObject().put("type", "json_object"))
        val resp = postJson(deepseekUrl, body, deepseekKey, CLOUD_READ_TIMEOUT_MS)
        val content = resp.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optString("content") ?: ""
        return parseDraft(content)
    }

    /** 解析起草结果，按 fit 降序。字段缺失时返回空表（面板会显示"未生成候选回复"）。 */
    private fun parseDraft(content: String): List<RankedReply> {
        val obj = try {
            JSONObject(content)
        } catch (e: Exception) {
            Log.w(TAG, "draft json parse failed: ${e.message}")
            return emptyList()
        }
        val arr = obj.optJSONArray("replies") ?: return emptyList()
        val out = ArrayList<RankedReply>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val text = o.optString("text").trim()
            if (text.isBlank()) continue
            // fit 缺失记 -1：排序后自然沉底，且渲染层不显示百分比 —— 不编造推荐度。
            val fit = if (o.has("fit")) o.optDouble("fit", -1.0).coerceIn(0.0, 1.0) else -1.0
            out.add(RankedReply(text, fit))
        }
        return out.sortedByDescending { it.prob }.take(3)
    }

    /** 备用路径：让 OpenRouter 上的生成式模型给出 3 条候选回复（国内需代理）。 */
    private fun generateCandidates(snapshot: ChatSnapshot, relationship: String): List<String> {
        val convo = snapshot.messages.takeLast(10).joinToString("\n") {
            (if (it.side == "me") "我" else "对方") + "：" + it.text
        }
        val sys = "你是中文职场沟通助手，帮用户回复工作消息。对方通常是用户的上级或同事。" +
            "只输出一个 JSON 数组，含且仅含 3 条候选回复文本。三条策略必须不同：" +
            "(1) 稳妥接住，并明确自己交付什么、什么时候；" +
            "(2) 以请教口吻确认职责归口或所需资源，不直接拒绝；" +
            "(3) 简短回应，为后续确认留出空间。" +
            "每条不超过 50 字。口吻专业克制、不卑不亢，符合中国企业即时通讯习惯。" +
            "不要承诺职责范围之外的事，不要认领尚未确认的责任，不要空泛表态。" +
            "不要解释，不要任何额外文字，直接输出 JSON 数组。"
        val user = "我的角色：$relationship\n\n最近对话：\n$convo\n\n请给出 3 条候选回复。"
        val messages = JSONArray()
            .put(JSONObject().put("role", "system").put("content", sys))
            .put(JSONObject().put("role", "user").put("content", user))
        val body = JSONObject()
            .put("model", replyModel)
            .put("messages", messages)
            .put("temperature", 0.8)
        val resp = postJson(chatUrl, body, openRouterKey, 25_000)
        val content = resp.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optString("content") ?: ""
        return parseThree(content)
    }

    private fun parseThree(content: String): List<String> {
        val start = content.indexOf('[')
        val end = content.lastIndexOf(']')
        if (start >= 0 && end > start) {
            try {
                val arr = JSONArray(content.substring(start, end + 1))
                val out = ArrayList<String>()
                for (i in 0 until arr.length()) out.add(arr.getString(i).trim())
                if (out.size >= 3) return out.take(3)
                while (out.size < 3) out.add("（稍等，我看下）")
                return out
            } catch (_: Exception) { }
        }
        val lines = content.split("\n").map { it.trim().trimStart('-', '*', '1', '2', '3', '.', ' ', '"') }
            .filter { it.isNotBlank() }
        val out = lines.take(3).toMutableList()
        while (out.size < 3) out.add("（稍等，我看下）")
        return out
    }

    // ------------------------------------------------------- questions 协议解析

    /**
     * 取一道是非题的 p_true。字段缺失或值不是有限数时返回 null。
     *
     * 为什么必须挡这一下：`optDouble` 在键不存在时返回 NaN，而 NaN 会一路流到
     * 渲染层的 `1.0 - p`，再进 `roundToInt()` 直接抛异常，整个面板就白了。
     * 模型少答一题不该让 UI 崩掉。
     */
    private fun pTrue(answers: JSONObject, key: String): Double? {
        val o = answers.optJSONObject(key) ?: return null
        if (!o.has("noul")) return null
        val v = o.optDouble("noul", Double.NaN)
        return if (v.isNaN()) null else v
    }

    private fun parseChoice(o: JSONObject?): Choice? {
        o ?: return null
        val probs = HashMap<String, Double>()
        o.optJSONObject("probabilities")?.let { p ->
            p.keys().forEach { k -> probs[k] = p.optDouble(k) }
        }
        return Choice(o.optString("choice"), o.optDouble("confidence", 0.0), probs)
    }

    private fun parseScore(o: JSONObject?): Score? {
        o ?: return null
        val legend = o.optJSONObject("legend")
        val maxLevel = legend?.keys()?.asSequence()?.mapNotNull { it.toIntOrNull() }?.maxOrNull() ?: 9
        return Score(o.optDouble("score", 0.0), o.optDouble("confidence", 0.0), maxLevel)
    }

    private fun parseRanked(o: JSONObject?, candidates: List<String>): List<RankedReply> {
        val keys = listOf("reply_a", "reply_b", "reply_c")
        val probs = o?.optJSONObject("probabilities")
        val list = candidates.mapIndexed { i, text ->
            RankedReply(text, probs?.optDouble(keys.getOrElse(i) { "" }, 0.0) ?: 0.0)
        }
        return list.sortedByDescending { it.prob }
    }

    private fun emptyAnalysis(start: Long, err: String, ruleHits: List<JevWorkRules.Hit>) = Analysis(
        hasSubtext = null, shiftingBlame = null, shiftingWork = null,
        informingOnly = null, needsRecord = null, impliedDeadline = null,
        whatTheyWant = null, bestAction = null, riskLevel = null,
        rankedReplies = emptyList(),
        latencyMs = System.currentTimeMillis() - start,
        error = err,
        ruleHits = ruleHits
    )

    // ------------------------------------------------------------------ 网络

    /**
     * 本地服务是否在线。局域网地址会随换网络而失效，先做一次 3 秒超时的健康探测，
     * 避免主请求（读超时 10 分钟）白等。
     */
    private fun ensureLocalReachable() {
        var conn: HttpURLConnection? = null
        try {
            conn = (URL("$localJevBase/health").openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 3000
                readTimeout = 3000
            }
            val code = conn.responseCode
            if (code !in 200..299) throw RuntimeException("健康检查返回 HTTP $code")
        } catch (e: Exception) {
            throw RuntimeException("连不上本地服务 $localJevBase：${e.message ?: e.javaClass.simpleName}")
        } finally {
            conn?.disconnect()
        }
    }

    /** POST JSON，对 429/529 做指数退避重试（最多 3 次）。4xx 不重试。 */
    private fun postJson(
        urlStr: String,
        body: JSONObject,
        bearer: String,
        readTimeoutMs: Int,
        headers: Map<String, String> = emptyMap(),
    ): JSONObject {
        var attempt = 0
        var lastErr: Exception? = null
        while (attempt < 3) {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 15_000
                    // 本地 NanoJev 是一次性预填几万 token，可能数十秒到数分钟；
                    // 云端约 1 秒。两条路用不同超时，避免本地被误判为失败。
                    this.readTimeout = readTimeoutMs
                    doOutput = true
                    setRequestProperty("Authorization", "Bearer $bearer")
                    setRequestProperty("Content-Type", "application/json")
                    setRequestProperty("X-Title", "Jev Assistant")
                    headers.forEach { (k, v) -> setRequestProperty(k, v) }
                }
                val bytes = body.toString().toByteArray(Charsets.UTF_8)
                conn.outputStream.use { os: OutputStream -> os.write(bytes) }
                val code = conn.responseCode
                if (code == 429 || code == 529) {
                    attempt++
                    Thread.sleep(500L * (1L shl attempt))
                    continue
                }
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val text = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
                if (code !in 200..299) throw RuntimeException("HTTP $code: ${text.take(200)}")
                return JSONObject(text)
            } catch (e: Exception) {
                lastErr = e
                if (e.message?.contains("HTTP 4") == true) throw e // client error: no retry
                attempt++
                if (attempt < 3) Thread.sleep(500L * (1L shl attempt))
            } finally {
                conn?.disconnect()
            }
        }
        throw lastErr ?: RuntimeException("request failed")
    }

    /**
     * 把底层网络异常翻译成人能看懂、且**带诊断信息**的文案。
     *
     * Android 的 ConnectException 消息里其实藏着关键线索：
     *   failed to connect to /192.168.1.10 (port 8788) from /192.168.1.20 (port 45231)
     *       after 3000ms: isConnected failed: ETIMEDOUT
     *   └─ 目标（Mac）地址 ────────────────┘  └─ 手机自己的 IP ─┘  └─ 真实原因 ─┘
     * 把「手机 IP」抠出来显示，用户一眼就能判断两边是不是同一网段。
     */
    private fun readableError(e: Exception): String {
        val m = e.message ?: e.javaClass.simpleName
        val phoneIp = Regex("from /([0-9.]+)").find(m)?.groupValues?.get(1)
        val pair = if (phoneIp != null && usingLocalJev) {
            "\n手机 IP：$phoneIp　Mac 地址：$localJevBase"
        } else ""

        // ---- DeepSeek：按官方错误码给具体处置建议 ----
        if (usingDeepSeek) {
            return when {
                m.contains("HTTP 401") -> "DeepSeek 密钥无效（401）。请到 platform.deepseek.com 重新复制密钥。"
                m.contains("HTTP 402") -> "DeepSeek 账户余额不足（402）。充值后即可恢复。"
                m.contains("HTTP 429") -> "DeepSeek 请求过于频繁（429）。稍等几秒再试。"
                m.contains("HTTP 400") -> "请求被 DeepSeek 拒绝（400）：$m"
                m.contains("HTTP 5") -> "DeepSeek 服务端异常：$m"
                m.contains("ETIMEDOUT") || m.contains("timed out") -> "连接 DeepSeek 超时。检查手机网络后重试。"
                m.contains("Unable to resolve host") -> "无法解析 api.deepseek.com，检查手机网络。"
                m.contains("返回空内容") -> "DeepSeek 返回了空内容，重试一次通常即可。"
                else -> "判断失败：$m"
            }
        }

        val where = if (usingLocalJev) "本地服务 $localJevBase" else "OpenRouter"
        return when {
            m.contains("HTTP 401") ->
                if (usingLocalJev) "本地服务令牌校验失败（401）" else "密钥无效或未设置（401）"

            m.contains("HTTP 4") -> "请求被拒：$m"

            // 超时：地址不对、或网络根本不通（不同 WiFi / 访客网络 / AP 隔离）
            m.contains("ETIMEDOUT") || m.contains("timed out") || m.contains("timeout") ->
                if (usingLocalJev)
                    "连不上 $localJevBase —— 超时无响应。$pair\n" +
                        "本地判断已停用，仅作调试用。请回设置页把「本地 NanoJev 地址」改成 Mac 当前的局域网地址；" +
                        "仍连不上就是手机与 Mac 不在同一个 WiFi。"
                else "等待 $where 超时；稍后重试"

            // 连接被拒：网络是通的，只是那个地址上没人监听
            m.contains("ECONNREFUSED") || m.contains("Connection refused") ->
                if (usingLocalJev)
                    "网络是通的，但 $localJevBase 上没有服务在监听。\n" +
                        "Mac 上的 NanoJev 服务可能没启动 —— 双击桌面「启动Jev服务.command」。"
                else "无法连接网络"

            m.contains("Unable to resolve host") ->
                "地址写错了（无法解析）：$localJevBase"

            m.contains("Failed to connect") ->
                if (usingLocalJev)
                    "连不上 $localJevBase。$pair\n" +
                        "本地判断已停用，仅作调试用。要恢复请在设置页手动填写 Mac 的局域网地址" +
                        "（Mac 终端执行 ipconfig getifaddr en0 可查）；仍失败就确认手机与 Mac 连的是同一个 WiFi。"
                else "无法连接网络"

            else -> "分析失败：$m"
        }
    }

    companion object {
        private const val TAG = "JEVASSIST"

        /** 本地 NanoJev 的读超时：10 分钟，够一次完整 9 题推理跑完。 */
        const val LOCAL_READ_TIMEOUT_MS = 600_000

        /** 云端判断的读超时：60 秒。大模型出 JSON 通常 3–8 秒，留足余量。 */
        const val CLOUD_READ_TIMEOUT_MS = 60_000
    }
}

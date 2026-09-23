package com.jev.probe.core

import android.content.Context

/**
 * App-private config store.
 *
 * 判断后端有三条路，**优先级自上而下**（[judgeBackendLabel] 与 [JevClient] 必须一致）：
 *   1. DeepSeek 云端（[deepseekKey] 非空）—— 当前唯一可用的判断源；
 *   2. 本地 NanoJev（[localJevUrl] 非空）—— 保留代码，但**实测判断无效**，见下；
 *   3. OpenRouter（[openRouterKey] 非空）—— 原伴侣模型，已停用。
 *
 * 关于第 2 条为什么还在但默认关掉
 * -----------------------------
 * 2026-09-23 的 state 敏感性对照实验证明：本地 Qwen3-0.6B 的输出与输入对话**无关**，
 * 每题恒定（5 组逻辑相反的对话，极差仅 1.8 个百分点）。它做不了这个判断。
 * 代码留着是为了将来换更大底座时能直接接回，DEFAULT_LOCAL_JEV 因此改为空字符串，
 * 不再默认启用。
 *
 * Key handling: stored in app-private SharedPreferences (not world-readable,
 * never logged, never in code/git).
 */
class Prefs(context: Context) {

    private val sp = context.getSharedPreferences("jev_assistant", Context.MODE_PRIVATE)

    // ------------------------------------------------------------- 判断后端

    /**
     * DeepSeek 官方密钥。**判断的主后端**，在 https://platform.deepseek.com 申请。
     *
     * 为什么判断必须走它：本地那个 0.6B 模型对中文职场话术完全在分布外，
     * 输出的概率与对话内容无关（已用对照实验证伪）。DeepSeek 是中文强模型，
     * 这类"这句话是不是在甩锅"的判断正是它的强项。
     */
    var deepseekKey: String
        get() = sp.getString(K_DS_KEY, "") ?: ""
        set(v) = sp.edit().putString(K_DS_KEY, v.trim()).apply()

    /** DeepSeek 模型名；默认 deepseek-chat，一般不用改。 */
    var deepseekModel: String
        get() = sp.getString(K_DS_MODEL, DEFAULT_DS_MODEL) ?: DEFAULT_DS_MODEL
        set(v) = sp.edit().putString(K_DS_MODEL, v.trim().ifBlank { DEFAULT_DS_MODEL }).apply()

    /** True when DeepSeek should be used for judgments. */
    val usesDeepSeek: Boolean get() = deepseekKey.isNotBlank()

    /**
     * Local NanoJev decision service base URL, e.g. "http://192.168.1.23:8788".
     *
     * ⚠️ 已实测判断无效（输出与对话内容无关），默认留空不再启用。
     * 仅当将来把 checkpoints 换成更大的底座模型后才有意义。
     */
    var localJevUrl: String
        get() = sp.getString(K_LOCAL_JEV, DEFAULT_LOCAL_JEV)?.trim()?.trimEnd('/') ?: ""
        set(v) = sp.edit().putString(K_LOCAL_JEV, v.trim().trimEnd('/')).apply()

    /** True when the local NanoJev service should be used for judgments. */
    val usesLocalJev: Boolean get() = localJevUrl.isNotBlank()

    /**
     * OpenRouter 密钥。**备用通道，一般不用填。**
     *
     * 历史用途有二：判断（伴侣模型）+ 起草候选回复。判断早已停用；起草候选回复
     * 自 2026-09-23 起也改由 DeepSeek 一次调用完成（见 `JevClient.draftViaDeepSeek`），
     * 所以**填了 DeepSeek 密钥就整个 App 都可用了**，不必再备 OpenRouter。
     *
     * 保留字段的原因：OpenRouter 上的模型可换（`replyModel`），将来若想试别的底座，
     * 填上它即可作为兜底。以及 —— openrouter.ai 在国内需代理，实际多半连不上。
     */
    var openRouterKey: String
        get() = sp.getString(K_KEY, "") ?: ""
        set(v) = sp.edit().putString(K_KEY, v.trim()).apply()

    /** 备用通道（OpenRouter）用的生成模型。DeepSeek 路径不使用此值。 */
    var replyModel: String
        get() = sp.getString(K_REPLY_MODEL, DEFAULT_REPLY_MODEL) ?: DEFAULT_REPLY_MODEL
        set(v) = sp.edit().putString(K_REPLY_MODEL, v.trim()).apply()

    /** 判断后端是否可用：DeepSeek 密钥、本地服务、或 OpenRouter 密钥，任一即可。 */
    fun canAnalyze(): Boolean = usesDeepSeek || usesLocalJev || openRouterKey.isNotBlank()

    /**
     * 起草候选回复是否可用。**与判断同源** —— DeepSeek 一次调用同时产出文本与推荐度，
     * 所以有 DeepSeek 密钥就够了；没有时才回落到 OpenRouter 备用通道。
     */
    fun canDraftReplies(): Boolean = usesDeepSeek || openRouterKey.isNotBlank()

    /** 供设置页与首页展示；顺序必须与 [JevClient] 的选取逻辑一致。 */
    fun judgeBackendLabel(): String = when {
        usesDeepSeek -> "DeepSeek 云端（$deepseekModel）"
        usesLocalJev -> "本地 NanoJev（$localJevUrl）"
        openRouterKey.isNotBlank() -> "OpenRouter 云端"
        else -> "未配置"
    }

    fun hasKey(): Boolean = openRouterKey.isNotBlank()

    // ---------------------------------------------------------------- 其它

    /** Free-text describing who the other person is; goes into Jev's state. */
    var relationship: String
        get() = sp.getString(K_REL, DEFAULT_REL) ?: DEFAULT_REL
        set(v) = sp.edit().putString(K_REL, v).apply()

    /** Master on/off for showing the overlay + running analysis. */
    var enabled: Boolean
        get() = sp.getBoolean(K_ENABLED, true)
        set(v) = sp.edit().putBoolean(K_ENABLED, v).apply()

    /**
     * Conversation whitelist: titles the assistant is allowed to act on. Empty
     * set means "all conversations". Stored as a plain string set.
     */
    var whitelist: Set<String>
        get() = sp.getStringSet(K_WHITELIST, emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet(K_WHITELIST, v).apply()

    /** Overlay panel opacity, 60..100 (%). Lower lets the chat show through. */
    var overlayOpacity: Int
        get() = sp.getInt(K_OPACITY, 92).coerceIn(60, 100)
        set(v) = sp.edit().putInt(K_OPACITY, v.coerceIn(60, 100)).apply()

    /** Remembered vertical position of the bubble (px); -1 = default. */
    var bubbleY: Int
        get() = sp.getInt(K_BUBBLE_Y, -1)
        set(v) = sp.edit().putInt(K_BUBBLE_Y, v).apply()

    /** Remembered horizontal position of the bubble (px); -1 = default. */
    var bubbleX: Int
        get() = sp.getInt(K_BUBBLE_X, -1)
        set(v) = sp.edit().putInt(K_BUBBLE_X, v).apply()

    /** Auto-analyze on every incoming message; if false, user taps to analyze. */
    var autoAnalyze: Boolean
        get() = sp.getBoolean(K_AUTO, true)
        set(v) = sp.edit().putBoolean(K_AUTO, v).apply()

    fun isAllowed(title: String?): Boolean {
        val wl = whitelist
        if (wl.isEmpty()) return true
        if (title == null) return false
        return wl.any { title.contains(it) }
    }

    companion object {
        private const val K_KEY = "openrouter_key"
        private const val K_DS_KEY = "deepseek_key"
        private const val K_DS_MODEL = "deepseek_model"
        private const val K_LOCAL_JEV = "local_jev_url"
        private const val K_REPLY_MODEL = "reply_model"
        private const val K_REL = "relationship"
        private const val K_ENABLED = "enabled"
        private const val K_WHITELIST = "whitelist"
        private const val K_OPACITY = "overlay_opacity"
        private const val K_BUBBLE_Y = "bubble_y"
        private const val K_BUBBLE_X = "bubble_x"
        private const val K_AUTO = "auto_analyze"

        /**
         * 本地 NanoJev 服务地址。
         *
         * **默认留空** —— 2026-09-23 的对照实验证明它的判断输出与对话内容无关
         * （5 组逻辑相反的 state 极差仅 1.8 个百分点），做不了职场判断。
         * 保留字段是为了将来换更大底座时能直接启用；填了地址就会优先于
         * OpenRouter，但仍低于 DeepSeek。
         */
        const val DEFAULT_LOCAL_JEV = ""

        // Reply drafting model on OpenRouter. DeepSeek is region-available in CN,
        // strong in Chinese, and cheap (Gemini/OpenAI are region-blocked here).
        const val DEFAULT_REPLY_MODEL = "deepseek/deepseek-chat-v3.1"

        /** DeepSeek 官方对话模型。 */
        const val DEFAULT_DS_MODEL = "deepseek-chat"

        const val DEFAULT_REL =
            "对方是我的上级领导；from=me 的是我发的，from=other 的是对方（领导或同事）发给我的"
    }
}

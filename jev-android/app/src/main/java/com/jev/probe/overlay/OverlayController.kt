package com.jev.probe.overlay

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.jev.probe.core.Analysis
import com.jev.probe.core.ChatSnapshot
import com.jev.probe.core.Choice
import com.jev.probe.core.Prefs
import com.jev.probe.core.RankedReply
import com.jev.probe.jev.JevLabels
import com.jev.probe.jev.JevWorkRules
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Floating overlay: a small draggable bubble that expands into a translucent
 * panel showing Jev's read of the chat plus 3 ranked candidate replies. All
 * actions are copy / fill — never send.
 *
 * Design goals: let the chat show through (adjustable opacity), keep the signal
 * scannable (danger badge + intent headline + reply cards), and stay out of the
 * way (draggable bubble that snaps to the edge and remembers its position).
 */
class OverlayController(private val ctx: Context) {

    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val prefs = Prefs(ctx)
    private var root: FrameLayout? = null
    private var bubble: TextView? = null
    private var dangerDot: View? = null
    private var panel: LinearLayout? = null
    private var contentBox: LinearLayout? = null
    private var expanded = false
    private var lp: WindowManager.LayoutParams? = null

    var onManualAnalyze: (() -> Unit)? = null

    /** Whether the overlay window is currently on screen. */
    fun isShowing(): Boolean = root != null

    private var lastJudgment: Analysis? = null
    private var lastFill: ((String) -> Unit)? = null

    private fun dp(v: Int) = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), ctx.resources.displayMetrics).roundToInt()

    private fun canOverlay(): Boolean = Settings.canDrawOverlays(ctx)

    private val screenW get() = ctx.resources.displayMetrics.widthPixels
    private val screenH get() = ctx.resources.displayMetrics.heightPixels

    /** Panel background: white with the user's opacity so the chat shows through. */
    private fun panelBg(): Int {
        val a = (prefs.overlayOpacity / 100f * 255).roundToInt().coerceIn(150, 255)
        return Color.argb(a, 255, 255, 255)
    }

    private fun card(radius: Int, color: Int, stroke: Boolean = false) = GradientDrawable().apply {
        cornerRadius = dp(radius).toFloat()
        setColor(color)
        if (stroke) setStroke(dp(1), Color.parseColor("#22000000"))
    }

    // ---------------------------------------------------------------- window

    private fun ensureRoot() {
        if (root != null) return
        if (!canOverlay()) { android.util.Log.w("JEVASSIST", "overlay: canDrawOverlays=false"); return }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = if (prefs.bubbleX in 0..(screenW - dp(52))) prefs.bubbleX else dp(8)
            y = if (prefs.bubbleY >= 0) prefs.bubbleY else dp(150)
        }
        lp = params

        val r = FrameLayout(ctx)
        val p = buildPanel()
        val bubbleWrap = buildBubble(params)
        r.addView(p)
        r.addView(bubbleWrap)
        root = r
        try { wm.addView(r, params) } catch (e: Exception) {
            android.util.Log.e("JEVASSIST", "overlay addView failed: ${e.message}"); root = null
        }
    }

    private fun buildBubble(params: WindowManager.LayoutParams): View {
        val wrap = FrameLayout(ctx).apply {
            layoutParams = FrameLayout.LayoutParams(dp(52), dp(52))
        }
        val b = TextView(ctx).apply {
            text = "Jev"
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.argb(235, 58, 122, 254))
            }
            layoutParams = FrameLayout.LayoutParams(dp(52), dp(52))
        }
        val dot = View(ctx).apply {
            background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.TRANSPARENT) }
            layoutParams = FrameLayout.LayoutParams(dp(12), dp(12)).apply {
                gravity = Gravity.TOP or Gravity.END
            }
        }
        wrap.addView(b)
        wrap.addView(dot)
        attachBubbleTouch(wrap, params)
        bubble = b; dangerDot = dot
        return wrap
    }

    private fun buildPanel(): LinearLayout {
        val p = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            background = card(18, panelBg(), stroke = true)
            elevation = dp(8).toFloat()
            setPadding(dp(14), dp(12), dp(14), dp(12))
            layoutParams = FrameLayout.LayoutParams(dp(316), FrameLayout.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(56) // sit just below the bubble
            }
        }
        // Header
        val header = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        header.addView(TextView(ctx).apply {
            text = "Jev 分析"; setTextColor(Color.parseColor("#111827")); textSize = 15f
            setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        header.addView(iconBtn("⚙") { openSettings() })
        header.addView(iconBtn("✕") { toggle() })
        p.addView(header)

        val scroll = ScrollView(ctx).apply {
            isVerticalScrollBarEnabled = false
            // Cap the height so the panel stays in the upper area and does not
            // cover WeChat's input box / keyboard. Scroll inside if taller.
            // 改版后一屏有 6 个"问题 + 概率"块（原来只有 3 行摘要），
            // 0.40 会逼用户频繁滚动，放宽到 0.46；填入后会自动收起，不挡操作。
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, (screenH * 0.46f).roundToInt()).apply { topMargin = dp(6) }
        }
        val content = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        scroll.addView(content)
        p.addView(scroll)
        contentBox = content
        panel = p
        return p
    }

    private fun iconBtn(glyph: String, onClick: () -> Unit) = TextView(ctx).apply {
        text = glyph; setTextColor(Color.parseColor("#6B7280")); textSize = 16f
        setPadding(dp(10), dp(2), dp(6), dp(2))
        setOnClickListener { onClick() }
    }

    // --------------------------------------------------------------- gestures

    private fun attachBubbleTouch(v: View, params: WindowManager.LayoutParams) {
        var startX = 0; var startY = 0; var touchX = 0f; var touchY = 0f
        var moved = false; var downTime = 0L; var longFired = false
        val longPress = Runnable {
            if (!moved) { longFired = true; showBubbleMenu() }
        }
        v.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x; startY = params.y; touchX = e.rawX; touchY = e.rawY
                    moved = false; longFired = false; downTime = System.currentTimeMillis()
                    v.postDelayed(longPress, 500); true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (e.rawX - touchX).toInt(); val dy = (e.rawY - touchY).toInt()
                    if (abs(dx) > dp(6) || abs(dy) > dp(6)) moved = true
                    // Keep a margin from both side edges: the extreme edge is MIUI's
                    // back-gesture zone, which steals touches and makes the bubble
                    // "stuck". Free positioning (no forced edge snap) also avoids it.
                    params.x = (startX + dx).coerceIn(dp(8), screenW - dp(60))
                    params.y = (startY + dy).coerceIn(dp(24), screenH - dp(120))
                    root?.let { runCatching { wm.updateViewLayout(it, params) } }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    v.removeCallbacks(longPress)
                    if (longFired) { true }
                    else if (moved) {
                        prefs.bubbleX = params.x; prefs.bubbleY = params.y; true  // stays where dropped
                    } else { toggle(); true }
                }
                MotionEvent.ACTION_CANCEL -> { v.removeCallbacks(longPress); true }
                else -> false
            }
        }
    }

    private fun showBubbleMenu() {
        val menu = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            background = card(12, panelBg(), stroke = true)
            elevation = dp(8).toFloat()
            setPadding(dp(4), dp(4), dp(4), dp(4))
            layoutParams = FrameLayout.LayoutParams(dp(150), ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(56) }
        }
        menu.addView(menuItem("打开设置") { openSettings(); root?.removeView(menu) })
        menu.addView(menuItem("隐藏助手（本次）") { hide() })
        menu.addView(menuItem("取消") { root?.removeView(menu) })
        root?.addView(menu)
    }

    private fun menuItem(label: String, onClick: () -> Unit) = TextView(ctx).apply {
        text = label; setTextColor(Color.parseColor("#111827")); textSize = 14f
        setPadding(dp(12), dp(10), dp(12), dp(10)); setOnClickListener { onClick() }
    }

    private fun openSettings() {
        runCatching {
            ctx.startActivity(Intent().setClassName(ctx, "com.jev.probe.SettingsActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        if (expanded) toggle()
    }

    private var collapsedX = dp(6)
    private var collapsedY = dp(150)

    private fun toggle() {
        expanded = !expanded
        val params = lp ?: return
        if (expanded) {
            // Open the panel from the left, fully on-screen and up high (clear of the
            // input box), regardless of which edge the bubble was snapped to.
            collapsedX = params.x; collapsedY = params.y
            params.x = dp(6)
            val maxTop = (screenH * 0.14f).roundToInt()
            if (params.y > maxTop) params.y = maxTop
            panel?.visibility = View.VISIBLE
        } else {
            panel?.visibility = View.GONE
            params.x = collapsedX; params.y = collapsedY  // bubble returns to where it was
        }
        android.util.Log.d("JEVASSIST", "overlay: toggle expanded=$expanded x=${params.x} y=${params.y} saved=($collapsedX,$collapsedY)")
        root?.let { runCatching { wm.updateViewLayout(it, params) } }
    }

    // ------------------------------------------------------------ public API

    fun showIdle(title: String?) {
        ensureRoot(); bubble?.alpha = 0.55f
        if (lastJudgment == null) setContent(listOf(bigButton("分析当前对话") { onManualAnalyze?.invoke() }))
    }

    private fun bigButton(label: String, onClick: () -> Unit) = TextView(ctx).apply {
        text = label; textSize = 14f; gravity = Gravity.CENTER
        setTextColor(Color.WHITE); setTypeface(typeface, Typeface.BOLD)
        background = card(12, Color.parseColor("#3A7AFE"))
        setPadding(dp(12), dp(11), dp(12), dp(11))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        setOnClickListener { onClick() }
    }

    fun showLoading() {
        ensureRoot(); bubble?.alpha = 1f
        setContent(listOf(hint("分析中…")))
        if (!expanded) toggle()
    }

    fun showError(msg: String) {
        ensureRoot(); bubble?.alpha = 1f
        setContent(listOf(
            line("出错了", "#DC2626", 14f, true),
            hint(msg)))
    }

    fun showJudgment(a: Analysis) {
        lastJudgment = a
        render(a, generating = true)
    }

    fun showReplies(ranked: List<RankedReply>, onFill: (String) -> Unit) {
        lastFill = onFill
        val a = lastJudgment?.copy(rankedReplies = ranked) ?: return
        lastJudgment = a
        render(a, generating = false)
    }

    fun toast(msg: String) = Toast.makeText(ctx, msg, Toast.LENGTH_SHORT).show()

    fun hide() {
        val r = root ?: return
        runCatching { wm.removeView(r) }
        root = null; bubble = null; panel = null; contentBox = null; dangerDot = null; expanded = false
    }

    // --------------------------------------------------------------- rendering

    private fun setContent(views: List<View>) {
        val c = contentBox ?: return
        c.removeAllViews(); views.forEach { c.addView(it) }
    }

    private fun render(a: Analysis, generating: Boolean) {
        ensureRoot(); bubble?.alpha = 1f
        panel?.background = card(18, panelBg(), stroke = true) // re-apply in case opacity changed
        val views = ArrayList<View>()

        // 风险等级置顶：职场场景下这是最需要一眼看到的信号。
        // 模型给的是 0..maxLevel 共 maxLevel+1 档，分母用"满分档数"，
        // 最高档显示成 maxLevel+1 分之 maxLevel（如 9 / 10），与用户预期一致。
        a.riskLevel?.let {
            val lvl = it.score.roundToInt()
            views.add(riskBadge(lvl, it.maxLevel + 1, (it.confidence * 100).roundToInt(), riskCause(a)))
            tintBubbleDanger(it.score)
        }

        // 一句话结论：只在单题把握 ≥ 60% 时才下，避免把摇摆的判断说成结论。
        verdict(a)?.let { views.add(verdictLine(it)) }

        // 关键词规则命中。**不来自模型** —— 是高置信的本地词表匹配，且会把原词摊开
        // 给用户看。因为可信度最高，排在模型结论之上。
        if (a.ruleHits.isNotEmpty()) views.add(ruleBlock(a.ruleHits))

        // 五道是非题。方向统一为 p_true =「是 / 需要留意」，两行都列、按概率降序，
        // 用户不必在脑子里做语义反转，也就不会看反。
        a.hasSubtext?.let { p ->
            views.add(questionBlock(JevLabels.SUBTEXT_Q, binaryRows(
                JevLabels.SUBTEXT_TRUE to p, JevLabels.SUBTEXT_FALSE to (1.0 - p))))
        }
        a.shiftingBlame?.let { p ->
            views.add(questionBlock(JevLabels.BLAME_Q, binaryRows(
                JevLabels.BLAME_TRUE to p, JevLabels.BLAME_FALSE to (1.0 - p))))
        }
        a.shiftingWork?.let { p ->
            views.add(questionBlock(JevLabels.WORK_Q, binaryRows(
                JevLabels.WORK_TRUE to p, JevLabels.WORK_FALSE to (1.0 - p))))
        }
        a.informingOnly?.let { p ->
            views.add(questionBlock(JevLabels.INFORM_Q, binaryRows(
                JevLabels.INFORM_TRUE to p, JevLabels.INFORM_FALSE to (1.0 - p))))
        }
        a.impliedDeadline?.let { p ->
            views.add(questionBlock(JevLabels.DEADLINE_Q, binaryRows(
                JevLabels.DEADLINE_TRUE to p, JevLabels.DEADLINE_FALSE to (1.0 - p))))
        }

        // 留痕建议单独成卡，不混在上面的概率列表里 —— 它是一条**行动指令**，
        // 把握低时干脆不出现，免得每次都弹一句废话。
        a.needsRecord?.let { p ->
            if (p >= LIKELY_PCT) {
                views.add(noticeCard(
                    "建议留痕 · 把握 ${(p * 100).roundToInt()}%",
                    "这条涉及责任、时限或资源，口头说完容易说不清。回完后用文字复述一遍，请对方确认。",
                    "#854F0B", "#FAEEDA"))
            }
        }

        // 辅助参考：多选与评分。实测判断力只有 20% 上下（6 选 1 均匀 = 16.7%），
        // 必须显著标注，否则「先确认归口 22%」会被当成明确推荐。
        if (a.whatTheyWant != null || a.bestAction != null) {
            views.add(divider())
            views.add(line("辅助参考 · 模型在这类多选题上判断力有限，别当结论", "#9CA3AF", 11.5f))
        }
        choiceBlock(JevLabels.WANT_Q, a.whatTheyWant, JevLabels.WANT)?.let { views.add(it) }
        choiceBlock(JevLabels.ACTION_Q, a.bestAction, JevLabels.ACTION)?.let { views.add(it) }

        views.add(divider())
        views.add(line("候选回复（按推荐度）", "#9CA3AF", 12f))
        if (generating) {
            views.add(hint("生成中…"))
        } else {
            val fill = lastFill ?: {}
            a.rankedReplies.forEachIndexed { i, r ->
                views.add(replyCard(i + 1, r.text, (r.prob * 100).roundToInt(), fill))
            }
            if (a.rankedReplies.isEmpty()) views.add(hint("（未生成候选回复）"))
        }
        views.add(reAnalyzeBtn())

        setContent(views)
        if (!expanded) toggle()
    }

    // ------------------------------------------------- 结论 / 规则命中 / 提示卡

    private class Verdict(val text: String, val fg: String, val bg: String)

    /**
     * 一句话结论。只在**单题把握 ≥ [LIKELY_PCT]** 时才给。
     *
     * 依据：本地 0.6B 模型在是非题上通常能给到 80% 以上；落在 50~60% 之间
     * 说明它自己也在摇摆，此时下结论就是误导。有风险项时优先报风险，
     * 只有全是"没事"才报安心 —— 宁可漏报，不可把中性的消息说成有问题。
     */
    private fun verdict(a: Analysis): Verdict? {
        val risky = ArrayList<String>()
        val calm = ArrayList<String>()
        if ((a.shiftingBlame ?: 0.0) >= LIKELY_PCT) risky.add("像在推责任，别口头认下")
        if ((a.shiftingWork ?: 0.0) >= LIKELY_PCT) risky.add("像在派活，先问清归口和资源")
        if ((a.hasSubtext ?: 0.0) >= LIKELY_PCT) risky.add("话里有深意，别只看字面")
        if ((a.informingOnly ?: 0.0) >= LIKELY_PCT) calm.add("只是知会，不用急着回")
        return when {
            risky.isNotEmpty() -> Verdict(risky.joinToString("；"), "#791F1F", "#FCEBEB")
            calm.isNotEmpty() -> Verdict(calm.joinToString("；"), "#27500A", "#EAF3DE")
            else -> null
        }
    }

    private fun verdictLine(v: Verdict): View = TextView(ctx).apply {
        text = v.text
        setTextColor(Color.parseColor(v.fg)); textSize = 13.5f
        setTypeface(typeface, Typeface.BOLD)
        background = card(10, Color.parseColor(v.bg))
        setPadding(dp(10), dp(8), dp(10), dp(8))
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(6) }
    }

    /**
     * 关键词命中区，按类别分组、把命中的**原词**摊开。
     *
     * 这一层的价值就在可解释性：用户看到「出了问题你负责」被标红，比看一个
     * 0.62 的数字有用得多 —— 他能马上判断"这话确实不对味"，也能看懂为什么报。
     */
    private fun ruleBlock(hits: List<JevWorkRules.Hit>): View {
        val col = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            background = card(10, Color.parseColor("#F3F4F6"))
            setPadding(dp(10), dp(8), dp(10), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(6) }
        }
        col.addView(TextView(ctx).apply {
            text = "话术特征（本地规则命中，最可信）"
            setTextColor(Color.parseColor("#6B7280")); textSize = 11.5f
        })
        JevWorkRules.byKind(hits).forEach { (kind, phrases) ->
            val row = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                setPadding(0, dp(3), 0, 0)
            }
            row.addView(TextView(ctx).apply {
                text = kind.label; setTextColor(Color.parseColor(kindColor(kind))); textSize = 12f
                setTypeface(typeface, Typeface.BOLD)
            })
            row.addView(TextView(ctx).apply {
                text = "  " + phrases.joinToString(" · ")
                setTextColor(Color.parseColor("#374151")); textSize = 12f
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            col.addView(row)
        }
        return col
    }

    private fun kindColor(k: JevWorkRules.Kind): String = when (k) {
        JevWorkRules.Kind.BLAME -> "#A32D2D"
        JevWorkRules.Kind.ASSIGN -> "#854F0B"
        JevWorkRules.Kind.PRESSURE -> "#BA7517"
        JevWorkRules.Kind.NOTIFY -> "#3B6D11"
    }

    /** 带底色的提示卡：用于留痕建议这类"要不要做某个动作"的结论。 */
    private fun noticeCard(title: String, body: String, fg: String, bg: String): View {
        val col = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            background = card(10, Color.parseColor(bg))
            setPadding(dp(10), dp(8), dp(10), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(8) }
        }
        col.addView(TextView(ctx).apply {
            text = title; setTextColor(Color.parseColor(fg)); textSize = 12.5f
            setTypeface(typeface, Typeface.BOLD)
        })
        col.addView(TextView(ctx).apply {
            text = body; setTextColor(Color.parseColor("#374151")); textSize = 12f
            setPadding(0, dp(3), 0, 0); setLineSpacing(dp(2).toFloat(), 1f)
        })
        return col
    }

    // ------------------------------------------------------ 概率分布版式

    /** noul 类问题：把 p_true / (1 - p_true) 展开成两行。 */
    private fun binaryRows(vararg pairs: Pair<String, Double>): List<Pair<String, Int>> =
        pairs.map { it.first to (it.second * 100).roundToInt() }
            .sortedByDescending { it.second }

    /**
     * choice 类问题：**按 JevLabels 里定义的固定顺序**从 probabilities 取值，
     * 而不是遍历返回的 map —— JSONObject 的键序不保证，会导致每次顺序都变。
     * 模型若新增了 labels 里没有的选项，则原样追加，避免静默丢失。
     */
    private fun choiceBlock(title: String, c: Choice?, labels: Map<String, String>): View? {
        c ?: return null
        val rows: List<Pair<String, Int>> = if (c.probabilities.isEmpty()) {
            // 分布缺失时的降级：只显示模型选中的那一项与其把握度
            listOf(JevLabels.label(labels, c.choice) to (c.confidence * 100).roundToInt())
        } else {
            val known = labels.keys.mapNotNull { k -> c.probabilities[k]?.let { k to it } }
            val unknown = c.probabilities.filterKeys { it !in labels.keys }.map { it.key to it.value }
            val all = (known + unknown)
                .sortedByDescending { it.second }
                .map { (k, p) -> JevLabels.label(labels, k) to (p * 100).roundToInt() }
            // 云端大模型返回的多选分布常是「一极全占 + 其余恰好 0」（本地小模型则是接近
            // 均匀）。0% 的行不带信息，却每条占一行 —— 面板上会连出三四行空进度条，看着
            // 像渲染坏了。滤掉；万一全被滤掉（极端情况）就退回原表，保证不出现空白块。
            val nonZero = all.filter { it.second > 0 }
            if (nonZero.isNotEmpty()) nonZero else all
        }
        if (rows.isEmpty()) return null
        return questionBlock(title, rows)
    }

    /** 一个问题块：粗体标题 + 最多 3 条概率行 + 其余折叠成一行。 */
    private fun questionBlock(title: String, rows: List<Pair<String, Int>>): View {
        val col = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(11) }
        }
        val head = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(3))
        }
        head.addView(TextView(ctx).apply {
            text = title
            setTextColor(Color.parseColor("#111827")); textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        // 本地 0.6B 模型在多选问题上常常给出接近均匀的分布（最高项也就 20% 上下）。
        // 若不提示，用户会把"只是随便聊聊 28%"误当成明确结论。低于阈值就明说是拿不准。
        if ((rows.firstOrNull()?.second ?: 0) < LOW_CONFIDENCE_PCT) {
            head.addView(TextView(ctx).apply {
                text = "模型拿不准"
                setTextColor(Color.parseColor("#B4B2A9")); textSize = 11.5f
            })
        }
        col.addView(head)
        rows.take(3).forEachIndexed { i, (label, pct) -> col.addView(probRow(label, pct, i == 0)) }
        val rest = rows.drop(3)
        if (rest.isNotEmpty()) {
            col.addView(TextView(ctx).apply {
                text = "其余 ${rest.size} 项共 ${rest.sumOf { it.second }}%"
                setTextColor(Color.parseColor("#9CA3AF")); textSize = 11.5f
                setPadding(0, dp(3), 0, 0)
            })
        }
        return col
    }

    /**
     * 一条概率行：左标签 + 右百分比 + 下方按比例填充的细条。
     * 细条用 LinearLayout 的 weight 实现（两条 weight 之和恒为 100），
     * 避免依赖布局完成后的实际宽度去算像素。
     */
    private fun probRow(label: String, pct: Int, top: Boolean): View {
        val col = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(3), 0, dp(3))
        }
        val row = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(TextView(ctx).apply {
            text = label; textSize = 12.5f
            setTextColor(Color.parseColor(if (top) "#111827" else "#6B7280"))
            if (top) setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        row.addView(TextView(ctx).apply {
            text = "$pct%"; textSize = 12.5f
            setTextColor(Color.parseColor(if (top) "#3A7AFE" else "#9CA3AF"))
            setTypeface(typeface, Typeface.BOLD)
        })
        col.addView(row)

        val p = pct.coerceIn(0, 100)
        val track = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            background = card(2, Color.parseColor("#EDF1F6"))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(3)
            ).apply { topMargin = dp(3) }
        }
        track.addView(View(ctx).apply {
            background = card(2, Color.parseColor(if (top) "#3A7AFE" else "#B9CDEA"))
            layoutParams = LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.MATCH_PARENT, p.toFloat())
        })
        track.addView(View(ctx).apply {
            layoutParams = LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.MATCH_PARENT, (100 - p).toFloat())
        })
        col.addView(track)
        return col
    }

    private fun riskBadge(lvl: Int, max: Int, confPct: Int, cause: RiskCause): View {
        val color = dangerColor(lvl)
        val row = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(2))
        }
        row.addView(TextView(ctx).apply {
            text = "风险 $lvl / $max"
            setTextColor(Color.WHITE); textSize = 13f; setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(10), dp(4), dp(10), dp(4))
            background = card(20, color)
        })
        row.addView(TextView(ctx).apply {
            text = "  " + dangerWord(lvl, cause); setTextColor(color); textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
        })
        // 本地模型返回的是 10 档分布，"把握度"即最高那一档的概率；低于阈值说明各档
        // 接近均匀，这个分数不该被当成确定结论。
        // 云端（DeepSeek）只回一个整数分、没有档位分布，`Score.confidence` 恒为 1.0，
        // 所以这条路不会触发这个提示 —— 这是有意的，不是漏了。
        if (confPct < LOW_CONFIDENCE_PCT) {
            row.addView(TextView(ctx).apply {
                text = "  把握仅 $confPct%"
                setTextColor(Color.parseColor("#B4B2A9")); textSize = 11.5f
            })
        }
        return row
    }

    private fun replyCard(rank: Int, text: String, pct: Int, onFill: (String) -> Unit): View {
        val top = rank == 1
        val cardBg = if (top) Color.parseColor("#EAF1FF") else Color.parseColor("#F3F4F6")
        val c = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            background = card(12, cardBg)
            setPadding(dp(10), dp(8), dp(10), dp(8))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(6) }
        }
        c.addView(TextView(ctx).apply {
            // pct < 0 = 模型没给推荐度。此时只显示序号，不显示"0%"这种会被误读成
            // "完全不合格"的数字。
            this.text = if (pct < 0) "#$rank" else "#$rank · ${pct}%"
            setTextColor(Color.parseColor("#3A7AFE")); textSize = 11f
            setTypeface(typeface, Typeface.BOLD)
        })
        c.addView(TextView(ctx).apply {
            this.text = text; setTextColor(Color.parseColor("#111827")); textSize = 14f
            setPadding(0, dp(3), 0, dp(7)); setLineSpacing(dp(2).toFloat(), 1f)
        })
        val btns = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        btns.addView(pill("复制", false) { copy(text) })
        // Fill, then collapse so the input box + keyboard are visible to review/send.
        btns.addView(pill("填入", true) { android.util.Log.d("JEVASSIST", "overlay: fill tapped"); onFill(text); if (expanded) toggle() })
        c.addView(btns)
        return c
    }

    private fun pill(label: String, primary: Boolean, onClick: () -> Unit) = TextView(ctx).apply {
        text = label; textSize = 13f; gravity = Gravity.CENTER
        setTypeface(typeface, Typeface.BOLD)
        setTextColor(if (primary) Color.WHITE else Color.parseColor("#3A7AFE"))
        background = card(18, if (primary) Color.parseColor("#3A7AFE") else Color.parseColor("#FFFFFF"), stroke = !primary)
        setPadding(dp(18), dp(6), dp(18), dp(6))
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { rightMargin = dp(8) }
        setOnClickListener { onClick() }
    }

    private fun reAnalyzeBtn() = TextView(ctx).apply {
        text = "重新分析"; textSize = 13f; gravity = Gravity.CENTER
        setTextColor(Color.parseColor("#6B7280"))
        setPadding(dp(10), dp(10), dp(10), dp(4))
        setOnClickListener { onManualAnalyze?.invoke() }
    }

    private fun tintBubbleDanger(score: Double) {
        val color = dangerColor(score.roundToInt())
        dangerDot?.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL; setColor(color); setStroke(dp(2), Color.WHITE)
        }
    }

    // --------------------------------------------------------------- helpers

    private fun line(text: String, color: String, size: Float, bold: Boolean = false) =
        TextView(ctx).apply {
            this.text = text; setTextColor(Color.parseColor(color)); textSize = size
            if (bold) setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(2), 0, dp(2))
        }

    private fun hint(text: String) = line(text, "#9CA3AF", 12f)

    private fun divider() = View(ctx).apply {
        setBackgroundColor(Color.parseColor("#1F000000"))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)).apply {
            topMargin = dp(8); bottomMargin = dp(4)
        }
    }

    private fun copy(text: String) {
        val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
        cm.setPrimaryClip(android.content.ClipData.newPlainText("jev_reply", text))
        toast("已复制")
    }

    private fun dangerColor(lvl: Int): Int = when {
        lvl >= 6 -> Color.parseColor("#DC2626")
        lvl >= 3 -> Color.parseColor("#D97706")
        else -> Color.parseColor("#16A34A")
    }

    /**
     * 风险定性的**主因**。用来把措辞贴合实际场景 ——
     * 明显在派活的场景说「有推责迹象」是错位的（推责和派活是两回事，
     * 应对方式也不同：派活要争边界，推责要争事实）。
     *
     * 三档措辞对应风险分的三个区间（见 [dangerWord]），
     * `high` 给 ≥8 分、`mid` 给 ≥6 分、`low` 给 ≥3 分。
     */
    private enum class RiskCause(val high: String, val mid: String, val low: String) {
        /** 把责任往你身上引 */
        BLAME("很可能背锅", "有推责迹象", "话锋在往你这边引"),

        /** 把不该你做的活交给你 */
        WORK("活压得不轻", "有派活迹象", "归口没说清"),

        /** 有弦外之音，但没往你身上推 */
        SUBTEXT("弦外之音很重", "有弦外之音", "话里有分寸"),

        /** 判断不出主因 —— 退回中性措辞，不硬点名 */
        UNCLEAR("风险偏高", "需要留意", "需留意边界")
    }

    /**
     * 从判断题里挑出主因。**取概率最高的那一项**，而不是按顺序硬套。
     *
     * 关键约束：只有最高项达到 [LIKELY_PCT] 才敢点名主因。都在 60% 以下说明
     * 模型自己也在摇摆，此时拿一个 40% 的读数去说「有派活迹象」就是编，
     * 退回 [RiskCause.UNCLEAR] 更诚实。
     *
     * 平手时按「推责 > 派活 > 深意」取 —— 严重程度递减，宁可说重不说轻。
     */
    private fun riskCause(a: Analysis): RiskCause {
        val blame = a.shiftingBlame ?: 0.0
        val work = a.shiftingWork ?: 0.0
        val sub = a.hasSubtext ?: 0.0
        if (maxOf(blame, work, sub) < LIKELY_PCT) return RiskCause.UNCLEAR
        return when {
            blame >= work && blame >= sub -> RiskCause.BLAME
            work >= sub -> RiskCause.WORK
            else -> RiskCause.SUBTEXT
        }
    }

    /** 风险分的文字定性。同一档分、不同主因，措辞不同。 */
    private fun dangerWord(lvl: Int, cause: RiskCause): String = when {
        lvl >= 8 -> cause.high
        lvl >= 6 -> cause.mid
        lvl >= 3 -> cause.low
        else -> "正常"
    }

    // 选项的中文标签与固定展示顺序统一由 JevLabels 提供，此处不再维护副本。
    companion object {
        /**
         * 最高概率低于此值即视为"没把握"，UI 会标注。
         *
         * 依据：多选题接近均匀时最高项与随机猜没有区别（6 选项均匀≈16.7%，
         * 7 选项≈14.3%，10 档评分≈10%）。此时必须显式标注，否则用户会把 20% 的
         * "最佳应对"误读成明确推荐。
         *
         * 注：35 这个值是当年按本地 0.6B 模型校准的（它输出常接近均匀）。
         * 换到云端大模型后概率分布会更集中，此阈值实际触发次数变少 ——
         * 保留它作兜底即可，不必上调（宁可少标，不可漏标）。
         */
        private const val LOW_CONFIDENCE_PCT = 35

        /**
         * 下"一句话结论"、以及给风险点名主因的门槛（60%）。
         *
         * 是非题的随机基线是 50%，所以落在 50~60% 等于"判断本身在犹豫"，此时下
         * 结论、或拿它去说"有派活迹象"，都是误导。60% 是个保守但够用的线。
         *
         * ⚠️ 别拿旧版本地小模型的"实测 80% 以上"来校准这个值 ——
         * 那个 80% 是**恒定输出**（5 段逻辑相反的话极差仅 1.8 个百分点），
         * 不是把握度。有意义的分布只能来自云端大模型。
         */
        private const val LIKELY_PCT = 0.60
    }
}

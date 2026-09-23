package com.jev.probe

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.jev.probe.core.ChatSnapshot
import com.jev.probe.core.LocalDiscovery
import com.jev.probe.core.Msg
import com.jev.probe.core.Prefs
import com.jev.probe.jev.JevClient
import java.util.concurrent.Executors
import kotlin.math.roundToInt

class SettingsActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())

    private val accent = Color.parseColor("#3A7AFE")
    private val ink = Color.parseColor("#111827")
    private val sub = Color.parseColor("#6B7280")

    private fun dp(v: Int) = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).roundToInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        window.decorView.setBackgroundColor(Color.parseColor("#F2F3F5"))

        val scroll = ScrollView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(22), dp(18), dp(28))
        }
        scroll.addView(root)

        root.addView(header("设置"))

        // --- 接口 ---
        root.addView(section("接口"))
        val card1 = card()
        card1.addView(label("DeepSeek 密钥（判断用 · 必须填）"))
        val dsEdit = edit(prefs.deepseekKey, "sk-...", password = true)
        card1.addView(dsEdit)
        card1.addView(text("判断「对方是不是在甩锅、在派活」和起草候选回复，都靠这一个密钥。" +
            "到 platform.deepseek.com 申请，充 10 元够用一两个月，单次判断不到一分钱。" +
            "不填则判断与候选回复都不可用。",
            12f, sub).apply { setPadding(0, dp(4), 0, 0) })
        card1.addView(label("判断模型"))
        val dsModelEdit = edit(prefs.deepseekModel, Prefs.DEFAULT_DS_MODEL)
        card1.addView(dsModelEdit)
        card1.addView(label("OpenRouter 密钥（备用通道 · 不用填）"))
        val keyEdit = edit(prefs.openRouterKey, "留空即可")
        card1.addView(keyEdit)
        card1.addView(text("填了上面的 DeepSeek 密钥，判断和候选回复就都通了，这里留空即可。" +
            "只有想换别的模型时才需要，且 openrouter.ai 在国内需代理，多半连不上。",
            12f, sub).apply { setPadding(0, dp(4), 0, 0) })
        card1.addView(label("备用通道的生成模型"))
        val modelEdit = edit(prefs.replyModel, Prefs.DEFAULT_REPLY_MODEL)
        card1.addView(modelEdit)
        card1.addView(label("本地 NanoJev 地址（已停用）"))
        val localEdit = edit(prefs.localJevUrl, "留空即可")
        card1.addView(localEdit)
        card1.addView(text("注意：实测这个本地模型的输出与对话内容无关 —— 同一道题换 5 组完全相反的对话，" +
            "结果只差 1.8 个百分点，做不了职场判断。留着只是将来换更大模型时备用，现在请留空。",
            12f, sub).apply { setPadding(0, dp(4), 0, 0) })
        root.addView(card1)

        // --- 分析 ---
        root.addView(section("分析"))
        val card2 = card()
        card2.addView(label("对方是谁（决定判断口径）"))
        val relEdit = edit(prefs.relationship, Prefs.DEFAULT_REL)
        card2.addView(relEdit)
        card2.addView(text("默认按「上级领导」写。对领导不能硬顶，只能接住并留痕；" +
            "换成平级、下属或客户时判断口径不同，可自行改写。",
            12f, sub).apply { setPadding(0, dp(4), 0, 0) })
        card2.addView(label("会话白名单（每行一个关键词，空=所有会话）"))
        val wlEdit = edit(prefs.whitelist.joinToString("\n"), "留空则对所有会话生效").apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE; minLines = 2
        }
        card2.addView(wlEdit)
        val autoRow = toggleRow("对方发消息时自动分析", prefs.autoAnalyze)
        card2.addView(autoRow)
        root.addView(card2)

        // --- 外观 ---
        root.addView(section("外观"))
        val card3 = card()
        val opacityLabel = label("悬浮窗不透明度：${prefs.overlayOpacity}%")
        card3.addView(opacityLabel)
        card3.addView(text("越低越透，越能看清下面的聊天", 12f, sub))
        val seek = SeekBar(this).apply {
            max = 40; progress = prefs.overlayOpacity - 60  // 60..100
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, u: Boolean) {
                    opacityLabel.text = "悬浮窗不透明度：${p + 60}%"
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        card3.addView(seek)
        root.addView(card3)

        // --- Actions ---
        val result = text("", 13f, sub).apply { setPadding(0, dp(12), 0, dp(4)) }
        root.addView(primaryBtn("保存") {
            prefs.deepseekKey = dsEdit.text.toString()
            prefs.deepseekModel = dsModelEdit.text.toString().ifBlank { Prefs.DEFAULT_DS_MODEL }
            prefs.openRouterKey = keyEdit.text.toString()
            prefs.replyModel = modelEdit.text.toString().ifBlank { Prefs.DEFAULT_REPLY_MODEL }
            prefs.localJevUrl = localEdit.text.toString()
            prefs.relationship = relEdit.text.toString().ifBlank { Prefs.DEFAULT_REL }
            prefs.whitelist = wlEdit.text.toString().split("\n").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
            prefs.autoAnalyze = (autoRow.tag as? Boolean) ?: true
            prefs.overlayOpacity = seek.progress + 60
            Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show()
        })
        root.addView(secondaryBtn("连通测试") {
            val dsKey = dsEdit.text.toString().trim()
            if (dsKey.isBlank() && localEdit.text.toString().isBlank()) {
                result.text = "请先填 DeepSeek 密钥（判断用）"
                return@secondaryBtn
            }
            // 用一条典型的"被派活"对话做样本，顺便能看出各维度是否给出不同答案。
            val demo = ChatSnapshot("连通测试", listOf(
                Msg("other", "在吗"), Msg("me", "在的，王总"),
                Msg("other", "上次说的那个报表你跟一下，我这两天要用")))
            result.text = "测试中…"
            worker.execute {
                val client = JevClient(
                    openRouterKey = keyEdit.text.toString().trim(),
                    replyModel = modelEdit.text.toString().trim().ifBlank { Prefs.DEFAULT_REPLY_MODEL },
                    localJevBase = localEdit.text.toString().trim().trimEnd('/'),
                    deepseekKey = dsKey,
                    deepseekModel = dsModelEdit.text.toString().trim().ifBlank { Prefs.DEFAULT_DS_MODEL },
                )
                val a = client.analyze(demo, prefs.relationship)
                val backend = client.backendName
                main.post {
                    fun pct(v: Double?) = v?.let { "${(it * 100).toInt()}%" } ?: "?"
                    result.text = if (a.error != null) "[$backend] 失败：${a.error}"
                    else "[$backend] 成功（耗时 ${a.latencyMs}ms）\n" +
                        "话外之意 ${pct(a.hasSubtext)} · 推责 ${pct(a.shiftingBlame)} · " +
                        "派活 ${pct(a.shiftingWork)}\n" +
                        "只是知会 ${pct(a.informingOnly)} · 该留痕 ${pct(a.needsRecord)} · " +
                        "隐含时限 ${pct(a.impliedDeadline)}\n" +
                        "风险 ${a.riskLevel?.score?.toInt() ?: "?"}/10 · " +
                        "规则命中 ${a.ruleHits.size} 处 · 候选回复 ${a.rankedReplies.size} 条"
                }
            }
        })
        root.addView(result)

        setContentView(scroll)
    }

    private fun toggleRow(labelText: String, initial: Boolean): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(12), 0, dp(2)); tag = initial
        }
        val lab = text(labelText, 14f, ink).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val sw = TextView(this).apply {
            text = if (initial) "开" else "关"; textSize = 13f; gravity = Gravity.CENTER
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (initial) Color.WHITE else sub)
            background = round(dp(10), if (initial) accent else Color.parseColor("#E5E7EB"))
            setPadding(dp(18), dp(6), dp(18), dp(6))
        }
        sw.setOnClickListener {
            val now = !((row.tag as? Boolean) ?: true); row.tag = now
            sw.text = if (now) "开" else "关"
            sw.setTextColor(if (now) Color.WHITE else sub)
            sw.background = round(dp(10), if (now) accent else Color.parseColor("#E5E7EB"))
        }
        row.addView(lab); row.addView(sw)
        return row
    }

    // atoms
    private fun header(t: String) = text(t, 24f, ink, bold = true).apply { setPadding(0, 0, 0, dp(4)) }
    private fun section(t: String) = text(t, 12f, sub, bold = true).apply { setPadding(dp(2), dp(16), 0, dp(6)) }
    private fun label(t: String) = text(t, 13f, ink, bold = true).apply { setPadding(0, dp(12), 0, dp(4)) }

    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = round(dp(14), Color.WHITE)
        setPadding(dp(14), dp(4), dp(14), dp(14))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    }

    private fun edit(value: String, hint: String, password: Boolean = false) = EditText(this).apply {
        setText(value); this.hint = hint; textSize = 14f; setTextColor(ink)
        background = round(dp(8), Color.parseColor("#F3F4F6"))
        setPadding(dp(10), dp(10), dp(10), dp(10))
        if (password) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(2) }
    }

    private fun text(t: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun primaryBtn(label: String, onClick: () -> Unit) = TextView(this).apply {
        text = label; textSize = 15f; gravity = Gravity.CENTER; setTypeface(typeface, Typeface.BOLD)
        setTextColor(Color.WHITE); background = round(dp(12), accent)
        setPadding(dp(16), dp(13), dp(16), dp(13))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(18) }
        setOnClickListener { onClick() }
    }

    private fun secondaryBtn(label: String, onClick: () -> Unit) = TextView(this).apply {
        text = label; textSize = 15f; gravity = Gravity.CENTER; setTypeface(typeface, Typeface.BOLD)
        setTextColor(accent); background = round(dp(12), Color.WHITE, stroke = true)
        setPadding(dp(16), dp(12), dp(16), dp(12))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(10) }
        setOnClickListener { onClick() }
    }

    private fun round(radius: Int, color: Int, stroke: Boolean = false) = GradientDrawable().apply {
        cornerRadius = radius.toFloat(); setColor(color); if (stroke) setStroke(dp(1), accent)
    }

    override fun onDestroy() { super.onDestroy(); worker.shutdownNow() }
}

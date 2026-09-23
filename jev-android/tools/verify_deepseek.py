#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek 判断通道端到端验证 —— 手机上发的同一套 prompt，跑 9 个场景。

要验证的核心命题只有一条：
    **模型真的在读对话，而不是恒定输出某个值。**

判据是"分离度"：把逻辑相反的场景喂进去，同一道是非题的概率必须被拉开。
上一版本地小模型就是栽在这里 —— 5 个相反场景的 p_true 全落在 84%±1，
range 只有 1.8 个百分点，等于没读输入。

密钥来源（按优先级）：
  1. 环境变量 DEEPSEEK_API_KEY
  2. ~/jev-work/nanojev/.deepseek_key  （一行纯密钥）

另外验证候选回复起草（表 4）：格式稳不稳、3 条是否真的策略不同、推荐度有没有拉开。

用法：
  DEEPSEEK_API_KEY=sk-xxx python3 tools/verify_deepseek.py
  python3 tools/verify_deepseek.py            # 走 .deepseek_key
  加 --html   额外输出一份 HTML 报告
  加 --draft  额外跑表 4（候选回复起草）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEYFILE = os.path.join(os.path.dirname(ROOT), "nanojev", ".deepseek_key")
URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

# ------------------------------------------------------------------ 场景设计
# 前 5 个是"状态敏感性"对照：逻辑上互相排斥，概率必须被拉开。
# 后 4 个是真实职场场景，各有一道题应当明显偏高。
SCENARIOS = [
    # ---- 对照组：状态敏感性 ----
    dict(id="A", group="对照", name="明显在推责",
         rel="对方是我的上级领导",
         msgs=[("other", "这个报表一直是你在跟的吧？我之前强调过好几次了，现在出了差错就是你的责任。")],
         expect={"shifting_blame": "high"}),
    dict(id="B", group="对照", name="正面表扬",
         rel="对方是我的上级领导",
         msgs=[("other", "这次客户反馈很好，你做得不错，继续保持。")],
         expect={"shifting_blame": "low"}),
    dict(id="C", group="对照", name="我自己认责",
         rel="对方是我的上级领导",
         msgs=[("me", "这块我确实没跟上，今晚我补齐了发您。"),
               ("other", "行，那你尽快。")],
         expect={"shifting_blame": "low"}),
    dict(id="D", group="对照", name="完全无关",
         rel="对方是我的上级领导",
         msgs=[("other", "明天公司食堂有活动，中午有盒饭。")],
         expect={"shifting_blame": "low", "shifting_work": "low"}),
    dict(id="E", group="对照", name="空对话（只有背景）",
         rel="对方是我的上级领导", msgs=[],
         expect={}),

    # ---- 真实场景：各有一道题应当拔尖 ----
    dict(id="1", group="场景", name="纯知会（应当：知会高、派活低）",
         rel="对方是我的上级领导；我发的是 me，对方发的是 other",
         msgs=[("other", "同步你一下，下周开始考勤改到钉钉打卡，不用回复。")],
         expect={"informing_only": "high", "shifting_work": "low"}),
    dict(id="2", group="场景", name="正常派活（应当：派活中低、无隐含期限）",
         rel="对方是我的上级领导；我发的是 me，对方发的是 other",
         msgs=[("other", "周五前把本月的用热台账整理一份发我，辛苦了。")],
         expect={"shifting_work": "low", "implied_deadline": "low"}),
    dict(id="3", group="场景", name="疑似派活·越界（应当：派活高）",
         rel="对方是我的上级领导；我发的是 me，对方发的是 other",
         msgs=[("other", "你比较熟这块，顺手把客服的满意度回访也一起弄了吧，具体你自己把握。")],
         expect={"shifting_work": "high", "implied_deadline": "high"}),
    dict(id="4", group="场景", name="疑似甩锅（应当：推责高）",
         rel="对方是我的上级领导；我发的是 me，对方发的是 other",
         msgs=[("other", "这个项目当初是你跟的，现在出了问题是你的责任，你自己跟领导解释。")],
         expect={"shifting_blame": "high"}),
]

BOOLS = ["has_subtext", "shifting_blame", "shifting_work",
         "informing_only", "needs_record", "implied_deadline"]

SYSTEM = ("你是职场沟通分析助手，服务对象是普通员工。你只输出一个 JSON 对象，"
          "不要写任何解释，不要加代码块标记，不要输出 JSON 之外的任何字符。")


def build_prompt(sc: dict) -> str:
    """与 JevClient.kt buildJudgePrompt() 逐字对应。两边改动必须同步。"""
    convo = "\n".join(
        ("我" if side == "me" else "对方") + "：" + text
        for side, text in sc["msgs"][-10:]
    ) or "（暂无消息）"
    return f"""
请分析下面这段工作对话，判断对方**最新那条**消息的真实意图。

【对话背景】{sc['rel']}
【最近对话】
{convo}

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
{{"has_subtext":0.0,"shifting_blame":0.0,"shifting_work":0.0,"informing_only":0.0,
"needs_record":0.0,"implied_deadline":0.0,
"what_they_want":{{"assign_work":0.0,"shift_blame":0.0,"seek_support":0.0,"seek_answer":0.0,"press_speed":0.0,"informing":0.0}},
"best_action":{{"confirm_scope":0.0,"ask_details":0.0,"restate_confirm":0.0,"give_plan":0.0,"accept_normal":0.0,"hold_and_watch":0.0,"private_talk":0.0}},
"risk_level":0}}
""".strip()


def get_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if k:
        return k
    if os.path.isfile(KEYFILE):
        with open(KEYFILE, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def call(key: str, sc: dict) -> dict:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_prompt(sc)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "stream": False,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = {401: "密钥无效", 402: "余额不足", 429: "请求过频"}.get(e.code, "")
        raise SystemExit(f"\nDeepSeek 返回 HTTP {e.code}（{hint}）：{detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"\n连不上 DeepSeek：{e.reason}")
    dt = (time.time() - t0) * 1000
    content = raw["choices"][0]["message"]["content"]
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        raise SystemExit(f"\n返回的不是合法 JSON：{content[:300]}")
    obj["_latency_ms"] = int(dt)
    obj["_usage"] = raw.get("usage", {})
    return obj


# ----------------------------------------------------------- 候选回复起草
# 2026-09-23 起，候选回复也走 DeepSeek（一次调用同时给文本与推荐度），
# 不再依赖 OpenRouter。下面这段 prompt 与 JevClient.kt draftViaDeepSeek() 逐字对应。

DRAFT_SYSTEM = ("你是中文职场沟通助手，服务对象是普通员工，对方通常是用户的上级或同事。"
                "你只输出一个 JSON 对象，不要写任何解释，不要加代码块标记。")

DRAFT_RULES = """【写法要求】给出 3 条可直接发送的回复，三条策略必须明显不同：
1. 稳妥接住：明确自己交付什么、什么时候给（不推诿，但也不扩大范围）；
2. 请教口吻确认归口：用问句把"这是谁的活、需要什么资源"问清楚，不直接拒绝；
3. 简短回应：先给一个不承诺具体范围的回复，为后续确认留出空间。
【硬约束】对方通常是上级，不能硬顶、不能直接拒绝、不能空泛表态；
不要承诺职责范围之外的事，不要认领尚未确认的责任；每条不超过 50 字；
口吻专业克制、不卑不亢，符合中国企业即时通讯习惯。

【fit 怎么给】0 到 1 的小数，表示这条回复在本场景下的推荐程度（越高越推荐）。
三条之间要拉开差距，不要都给 0.8 这种含糊值。"""

# 取三个反差场景：①纯知会（本不该大动干戈）、③越界派活（该出现确认归口）、
# ④甩锅（最该出现复述留痕）。预览页的三例就是这三个，跑它们才能把示意值换成实测值。
DRAFT_IDS = ["1", "3", "4"]


def build_draft_prompt(sc: dict) -> str:
    """与 JevClient.kt draftViaDeepSeek() 逐字对应。两边改动必须同步。"""
    convo = "\n".join(
        ("我" if side == "me" else "对方") + "：" + text
        for side, text in sc["msgs"][-10:]
    ) or "（暂无消息）"
    return f"""请以「我」的身份，回复下面这段工作对话里对方的**最新那条**消息。

【我的角色】{sc['rel']}
【最近对话】
{convo}

{DRAFT_RULES}
【输出格式】只输出下面这个 JSON，不要任何其它文字：
{{"replies":[{{"text":"回复正文","fit":0.0,"why":"一句话说明这条的策略"}}]}}"""


def call_draft(key: str, sc: dict):
    """返回 (items, 耗时ms, 错误)。items 为 (text, fit, why) 三元组列表。"""
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": DRAFT_SYSTEM},
            {"role": "user", "content": build_draft_prompt(sc)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.6,
        "stream": False,
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = {401: "密钥无效", 402: "余额不足", 429: "请求过频"}.get(e.code, "")
        return [], 0, f"HTTP {e.code}（{hint}）：{detail}"
    except urllib.error.URLError as e:
        return [], 0, f"连不上 DeepSeek：{e.reason}"
    dt = int((time.time() - t0) * 1000)
    content = raw["choices"][0]["message"]["content"]
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        return [], dt, f"返回的不是合法 JSON：{content[:200]}"
    arr = obj.get("replies")
    if not isinstance(arr, list):
        return [], dt, "JSON 里没有 replies 数组"
    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        t = str(it.get("text", "")).strip()
        if not t:
            continue
        f = it.get("fit")
        f = float(f) if isinstance(f, (int, float)) else -1.0
        out.append((t, max(-1.0, min(1.0, f)), str(it.get("why", "")).strip()))
    return out, dt, None


def run_draft(key: str) -> bool:
    """验证起草：JSON 稳不稳、3 条是否真的不同、推荐度有没有拉开。"""
    print("\n" + "=" * 78)
    print("表 4 · 候选回复起草（与判断同源，一次调用产出文本 + 推荐度）")
    print("=" * 78)
    all_ok = True
    by_id = {s["id"]: s for s in SCENARIOS}
    for sid in DRAFT_IDS:
        sc = by_id[sid]
        items, dt, err = call_draft(key, sc)
        print(f"\n[{sid}] {sc['name']}   ({dt} ms)")
        if err:
            print(f"   ❌ {err}")
            all_ok = False
            continue
        if len(items) < 3:
            print(f"   ❌ 只给出 {len(items)} 条，应为 3 条")
            all_ok = False
        texts = [t for t, _, _ in items]
        if len(set(texts)) < len(texts):
            print("   ❌ 有重复文本 —— 三条没有策略差异")
            all_ok = False
        fits = [f for _, f, _ in items]
        if any(f < 0 for f in fits):
            print("   ⚠️  有 fit 缺失（App 里该条不显示百分比，只显示序号）")
        elif len(set(fits)) == 1:
            print("   ⚠️  三条 fit 相同，推荐度没拉开（能显示，但排序无意义）")
        for i, (t, f, why) in enumerate(items, 1):
            pct = "  —" if f < 0 else f"{f * 100:3.0f}%"
            print(f"   #{i} [{pct}] {t}")
            if why:
                print(f"          策略：{why}")
        if len(items) >= 3 and len(set(texts)) == len(texts):
            print("   ✅ 格式与差异度通过")
    return all_ok


def fmt_pct(v) -> str:
    try:
        return f"{float(v) * 100:5.1f}%"
    except (TypeError, ValueError):
        return "  n/a"


def top_of(d: dict) -> str:
    if not isinstance(d, dict) or not d:
        return "-"
    k = max(d, key=lambda x: d[x])
    return f"{k}({d[k] * 100:.0f}%)"


def judge_range(rows: list, key: str) -> tuple:
    """返回 (min, max, 是否拉开)。是非题的分离度是本次验证的核心指标。"""
    vals = [r["ans"][key] for r in rows
            if isinstance(r["ans"].get(key), (int, float))]
    if len(vals) < 2:
        return None, None, False
    lo, hi = min(vals), max(vals)
    return lo, hi, (hi - lo) >= 0.25


def main() -> int:
    key = get_key()
    if not key:
        print("未找到 DeepSeek 密钥。请二选一：\n"
              "  1) export DEEPSEEK_API_KEY=sk-xxx\n"
              f"  2) 把密钥写入 {KEYFILE}（一行纯密钥，不要引号）\n"
              "\n密钥申请：https://platform.deepseek.com/api_keys", file=sys.stderr)
        return 2

    # 只跑起草（省 9 次判断请求）。
    # 为什么会需要：判断结果只在改 prompt 时才要重验，而起草的候选文本给预览页用，
    # 可能要反复取。
    if "--draft-only" in sys.argv:
        print(f"通道：DeepSeek 官方直连（{MODEL}）—— 只跑起草（表 4）\n")
        return 0 if run_draft(key) else 1

    print(f"通道：DeepSeek 官方直连（{MODEL}）")
    print(f"场景：{len(SCENARIOS)} 个（5 对照 + 4 场景）\n")

    rows = []
    for sc in SCENARIOS:
        try:
            ans = call(key, sc)
        except SystemExit:
            raise
        except Exception as e:                       # noqa: BLE001
            print(f"[{sc['id']}] {sc['name']} —— 失败：{e}")
            rows.append(dict(sc=sc, ans={}, err=str(e), latency=0))
            continue
        rows.append(dict(sc=sc, ans=ans, err=None,
                         latency=ans.get("_latency_ms", 0)))
        print(f"[{sc['id']}] {sc['name']}  ({rows[-1]['latency']} ms)")

    ok = [r for r in rows if not r["err"]]
    if not ok:
        print("\n全部请求失败，无结果可分析。", file=sys.stderr)
        return 1

    # ------------------------------------------------ 表 1：每场景 6 道是非题
    print("\n" + "=" * 78)
    print("表 1 · 各场景的是非题概率")
    print("=" * 78)
    head = f"{'场景':<26}" + "".join(f"{k[:9]:>11}" for k in BOOLS)
    print(head)
    print("-" * 78)
    for r in rows:
        if r["err"]:
            continue
        name = f"[{r['sc']['id']}] {r['sc']['name']}"
        line = f"{name[:24]:<26}"
        line += "".join(fmt_pct(r["ans"].get(k)).rjust(11) for k in BOOLS)
        print(line)

    # ------------------------------------------------ 表 2：分离度 + 期待方向
    print("\n" + "=" * 78)
    print("表 2 · 分离度（核心指标：range ≥ 25 个百分点才算「真的在读对话」）")
    print("=" * 78)
    print(f"{'题目':<20}{'最低':>9}{'最高':>9}{'range':>10}   判定")
    print("-" * 78)
    all_pass = True
    for k in BOOLS:
        lo, hi, good = judge_range(rows, k)
        if lo is None:
            print(f"{k:<20}{'—':>9}{'—':>9}{'—':>10}   数据不足")
            all_pass = False
            continue
        print(f"{k:<20}{lo * 100:8.1f}%{hi * 100:8.1f}%{(hi - lo) * 100:9.1f}pt   "
              f"{'✅ 拉开了' if good else '❌ 没拉开'}")
        if not good:
            all_pass = False

    # ------------------------------------------------ 表 3：期待方向核对
    print("\n" + "=" * 78)
    print("表 3 · 期待方向核对（high 应当高于全部 low）")
    print("=" * 78)
    by_id = {r["sc"]["id"]: r for r in rows if not r["err"]}
    for r in rows:
        if r["err"] or not r["sc"]["expect"]:
            continue
        sid = r["sc"]["id"]
        for k, want in r["sc"]["expect"].items():
            v = r["ans"].get(k)
            if not isinstance(v, (int, float)):
                continue
            others = [o["ans"].get(k) for oid, o in by_id.items() if oid != sid]
            others = [x for x in others if isinstance(x, (int, float))]
            if not others:
                continue
            if want == "high":
                ref = min(others)
                okk = v > ref
                cmp_txt = f"应最高，实际 {v*100:.0f}% vs 他场景最低 {ref*100:.0f}%"
            else:
                ref = max(others)
                okk = v < ref
                cmp_txt = f"应偏低，实际 {v*100:.0f}% vs 他场景最高 {ref*100:.0f}%"
            print(f"  {'✅' if okk else '❌'} [{sid}] {k:<18} {cmp_txt}")
            if not okk:
                all_pass = False

    # ------------------------------------------------ 表 4：选择与评分
    print("\n" + "=" * 78)
    print("表 4 · 选择项与风险分")
    print("=" * 78)
    print(f"{'场景':<26}{'对方想要':<26}{'建议动作':<24}{'风险'}")
    print("-" * 78)
    for r in rows:
        if r["err"]:
            continue
        name = f"[{r['sc']['id']}] {r['sc']['name']}"[:24]
        print(f"{name:<26}{top_of(r['ans'].get('what_they_want')):<26}"
              f"{top_of(r['ans'].get('best_action')):<24}"
              f"{r['ans'].get('risk_level', '-')}")

    # 完整分布：预览页要把每一行都照实画出来，只看 top 项会逼着人去猜其余值。
    print("\n" + "=" * 78)
    print("表 4b · 多选项完整分布（供预览页照实呈现）")
    print("=" * 78)
    for r in rows:
        if r["err"]:
            continue
        print(f"\n[{r['sc']['id']}] {r['sc']['name']}")
        for key, label in (("what_they_want", "对方想要什么"), ("best_action", "最佳应对")):
            d = r["ans"].get(key)
            if not isinstance(d, dict) or not d:
                print(f"   {label}：无数据")
                continue
            parts = sorted((kv for kv in d.items() if isinstance(kv[1], (int, float))),
                           key=lambda kv: -kv[1])
            print(f"   {label}：" + " | ".join(f"{k} {v * 100:.0f}%" for k, v in parts))
        print(f"   风险分：{r['ans'].get('risk_level', '-')}")

    # ------------------------------------------------ 表 4：候选回复起草
    if "--draft" in sys.argv:
        if not run_draft(key):
            all_pass = False

    # ------------------------------------------------ 结论
    print("\n" + "=" * 78)
    if all_pass:
        print("结论：✅ 全部通过 —— 模型确实在读对话内容，方向也正确。")
    else:
        print("结论：❌ 有项目未通过，见上表标 ❌ 处。")
    print("=" * 78)

    if "--html" in sys.argv:
        out = os.path.join(ROOT, "docs", "deepseek_verification.html")
        write_html(out, rows, all_pass)
        print(f"\nHTML 报告：{out}")

    return 0 if all_pass else 1


# ------------------------------------------------------------------ HTML 报告
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--tx:#1c1f23;--mut:#6b7280;
--ok:#15803d;--okbg:#e8f5ec;--bad:#b91c1c;--badbg:#fdecec;--hi:#b45309}
*{box-sizing:border-box}
body{margin:0;padding:28px 20px 60px;background:var(--bg);color:var(--tx);
font:14px/1.7 -apple-system,"PingFang SC","Helvetica Neue",sans-serif}
.wrap{max-width:1040px;margin:0 auto}
h1{font-size:21px;margin:0 0 6px}
.sub{color:var(--mut);font-size:13px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:18px}
h2{font-size:15px;margin:0 0 12px;padding-left:9px;border-left:3px solid #2563eb}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600;font-size:12px}
.bar{display:inline-block;height:8px;border-radius:4px;background:#93c5fd;
vertical-align:middle;margin-right:6px}
.pass{color:var(--ok);font-weight:600}
.fail{color:var(--bad);font-weight:600}
.tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;
background:var(--okbg);color:var(--ok)}
.tag.b{background:var(--badbg);color:var(--bad)}
.note{font-size:12px;color:var(--mut);margin-top:10px}
.banner{padding:14px 18px;border-radius:9px;font-weight:600;margin-bottom:18px}
.banner.ok{background:var(--okbg);color:var(--ok)}
.banner.bad{background:var(--badbg);color:var(--bad)}
"""


def _bar(v) -> str:
    if not isinstance(v, (int, float)):
        return ""
    return f'<span class="bar" style="width:{max(2, int(v * 70))}px"></span>'


def write_html(path: str, rows: list, all_pass: bool) -> None:
    ok = [r for r in rows if not r["err"]]
    p = []
    p.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    p.append('<title>DeepSeek 判断通道验证报告</title>')
    p.append(f"<style>{CSS}</style></head><body><div class='wrap'>")
    p.append("<h1>DeepSeek 判断通道验证报告</h1>")
    p.append("<div class='sub'>验证命题：模型是否真的在读对话，而不是恒定输出某个值。"
             "方法是把逻辑相反的场景喂进去，看同一道是非题的概率能否被拉开。</div>")
    p.append(f"<div class='banner {'ok' if all_pass else 'bad'}'>"
             f"{'全部通过' if all_pass else '存在未通过项'}"
             f" —— 共 {len(ok)}/{len(rows)} 个场景成功返回</div>")

    # 场景 × 概率
    p.append("<div class='card'><h2>表 1 · 各场景的是非题概率</h2><table>")
    p.append("<tr><th>场景</th>" + "".join(f"<th>{k}</th>" for k in BOOLS) + "</tr>")
    for r in ok:
        p.append(f"<tr><td>[{r['sc']['id']}] {r['sc']['name']}</td>" +
                 "".join(f"<td>{_bar(r['ans'].get(k))}"
                         f"{r['ans'].get(k, 0) * 100:.0f}%</td>" for k in BOOLS) + "</tr>")
    p.append("</table><div class='note'>蓝色条长度表示概率大小。"
             "若各行几乎一样长，说明模型没有读输入 —— 这正是旧的本地小模型的症状："
             "range 仅 1.8 个百分点。</div></div>")

    # 分离度
    p.append("<div class='card'><h2>表 2 · 分离度（核心指标）</h2><table>")
    p.append("<tr><th>题目</th><th>最低</th><th>最高</th><th>range</th><th>判定</th></tr>")
    for k in BOOLS:
        lo, hi, good = judge_range(rows, k)
        if lo is None:
            p.append(f"<tr><td>{k}</td><td colspan=4>数据不足</td></tr>")
            continue
        p.append(f"<tr><td>{k}</td><td>{lo*100:.1f}%</td><td>{hi*100:.1f}%</td>"
                 f"<td>{(hi-lo)*100:.1f}pt</td>"
                 f"<td class='{'pass' if good else 'fail'}'>"
                 f"{'✅ 拉开了' if good else '❌ 没拉开'}</td></tr>")
    p.append("</table><div class='note'>判通过线：range ≥ 25 个百分点。</div></div>")

    # 期待方向
    p.append("<div class='card'><h2>表 3 · 期待方向核对</h2><table>")
    p.append("<tr><th>场景</th><th>题目</th><th>实际</th><th>对照</th><th>判定</th></tr>")
    by_id = {r["sc"]["id"]: r for r in ok}
    for r in ok:
        for k, want in (r["sc"]["expect"] or {}).items():
            v = r["ans"].get(k)
            if not isinstance(v, (int, float)):
                continue
            others = [o["ans"].get(k) for oid, o in by_id.items() if oid != r["sc"]["id"]]
            others = [x for x in others if isinstance(x, (int, float))]
            if not others:
                continue
            if want == "high":
                ref, good, txt = min(others), v > min(others), f"他场景最低 {min(others)*100:.0f}%"
            else:
                ref, good, txt = max(others), v < max(others), f"他场景最高 {max(others)*100:.0f}%"
            p.append(f"<tr><td>[{r['sc']['id']}] {r['sc']['name']}</td><td>{k}</td>"
                     f"<td>{v*100:.0f}%</td><td>{txt}</td>"
                     f"<td class='{'pass' if good else 'fail'}'>"
                     f"{'✅' if good else '❌'} 应为{'偏高' if want == 'high' else '偏低'}</td></tr>")
    p.append("</table></div>")

    # 选择与评分
    p.append("<div class='card'><h2>表 4 · 选择项与风险分</h2><table>")
    p.append("<tr><th>场景</th><th>对方想要</th><th>建议动作</th><th>风险分</th></tr>")
    for r in ok:
        p.append(f"<tr><td>[{r['sc']['id']}] {r['sc']['name']}</td>"
                 f"<td>{top_of(r['ans'].get('what_they_want'))}</td>"
                 f"<td>{top_of(r['ans'].get('best_action'))}</td>"
                 f"<td>{r['ans'].get('risk_level', '-')}</td></tr>")
    p.append("</table></div>")

    usages = [r["ans"].get("_usage", {}) for r in ok]
    tin = sum(u.get("prompt_tokens", 0) for u in usages)
    tout = sum(u.get("completion_tokens", 0) for u in usages)
    lat = [r["latency"] for r in ok if r["latency"]]
    p.append("<div class='card'><h2>开销</h2><table>")
    p.append(f"<tr><td>输入 tokens</td><td>{tin:,}</td></tr>")
    p.append(f"<tr><td>输出 tokens</td><td>{tout:,}</td></tr>")
    if lat:
        p.append(f"<tr><td>单次延迟</td><td>{min(lat)} – {max(lat)} ms "
                 f"（均值 {sum(lat)//len(lat)} ms）</td></tr>")
    p.append("</table></div>")

    p.append("</div></body></html>")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(p))


if __name__ == "__main__":
    sys.exit(main())

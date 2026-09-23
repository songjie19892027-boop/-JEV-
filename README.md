[README.md](https://github.com/user-attachments/files/32550656/README.md)
# -JEV-
结合jev模型判断聊天风险，看你和同事的聊天是否甩锅、是否推活儿
# Jev 聊天助手 + 本地 NanoJev 判断服务

> **本项目为二次开发版**，基于上游 [jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis)（MIT）改造。
> 上游版权声明原样保留：`Copyright (c) 2026 Finderchangchang and the jev-chat contributors`。
> 「Jev 聊天助手」「jev-chat」为**上游项目名称**，本项目与上游**无隶属、无背书、非官方**关系。
> 使用边界见 [DISCLAIMER.md](DISCLAIMER.md)，署名与许可义务见 [NOTICE.md](NOTICE.md)。

把 `jev-chat-jarvis`（安卓对话副驾）原来的**云端 Jev 判断**，换成跑在你自己 Mac 上的
**NanoJev**（[TypeSafe Jev](https://typesafe.ai/) 的开源 0.6B 复刻，底座 Qwen3-0.6B）。

判断不再出设备、不再走 OpenRouter、不产生费用。

---

## 一、架构

```
┌─────────────────────┐        同一 WiFi         ┌──────────────────────────────┐
│  安卓手机            │  ──────────────────────▶ │  Mac (M4)                    │
│  Jev 聊天助手 APK    │  POST /api/alpha/decisions│  jev_server.py  :8788       │
│                     │  ◀────────────────────── │    └─ NanoJevEngine          │
│  无障碍读屏 → 悬浮窗 │      {answers:{...}}      │         └─ Qwen3-0.6B+决策头 │
└─────────────────────┘                          └──────────────────────────────┘
        │
        └── 回复起草（3 条候选）仍走 OpenRouter（NanoJev 是判断模型，不产文本）
```

**关键设计：服务端提供与 OpenRouter 同形的接口。**
安卓端只改了一个 base URL，其余业务逻辑（题目集、悬浮窗、排序、回填输入框）一行未动。

---

## 二、为什么是"服务化"而不是"塞进 APK"

| | 塞进 APK（端侧） | 服务化（本方案） |
|---|---|---|
| 单次分析 | 估算分钟级（**未实测**） | **13.0 s**（M4 MPS fp16） |
| APK 体积 | 350–650 MB | **10–12 MB** |
| 出门可用 | 可以 | 不行（需同一 WiFi）|
| 判断质量（跨域） | 同样不可预期 | 同样不可预期 |

端侧不可行的根因**不是模型太大，是模型的设计**：官方源码里 `prefix_sharing: False`，
每道题的**每个候选**都要独立编码一遍完整序列。app 一次发 8 道题、**34 条候选路径**，
合计 **8,413 token** 预填（实测值），且 34 条互不共享前缀。

> ⚠️ **数字更正**：早期方案评估里写的「37 条候选 / 约 3.9 万 token」是**高估**，
> 实测为 34 条候选 / 8,413 token。这使端侧的可行性比原先判断的**要好一些**，
> 但端侧方案从未真正跑过，上表的「分钟级」仍属**未实测估算**，不作为结论。

---

## 三、目录

```
jev-work/
├── nanojev/
│   ├── checkpoints/NanoJev-unified/   # 模型权重（2.22 GiB，来自 HuggingFace）
│   ├── src/                           # NanoJev 官方脚本（原样）
│   │   ├── train_toy_decisions.py     #   DecisionModel 定义
│   │   ├── predict_toy_decisions.py   #   校验/编码/解码（复用）
│   │   └── serve_decisions.py         #   官方服务（未用，作参照）
│   ├── server/
│   │   ├── nanojev_engine.py          # ★ Mac 适配推理引擎（替换 CUDA 硬依赖）
│   │   └── jev_server.py              # ★ Jev 协议兼容 HTTP 服务
│   ├── verify_local.py                # app 真实请求形状的端到端验证
│   ├── domain_probe.py                # 领域对照实验（中文聊天 vs 游戏）
│   ├── serve_apk.py                   # APK 局域网分发页（手机浏览器下载）
│   ├── selftest.sh                    # 一键自检：起服务→等就绪→打一次→收工
│   └── run_server.sh                  # 启动常驻服务
└── jev-android/                       # 改造后的安卓工程
    ├── app/src/main/java/com/jev/probe/ # 改动集中在 Prefs/JevClient/SettingsActivity
    ├── build_apk.sh                   # 一键构建（debug / release 自动分名）
    ├── jev-release.jks                # 本地自签密钥库 —— 不进仓库（.gitignore 已忽略）
    ├── jev-assistant-local-nanojev-debug.apk     # 12 MB —— 不进仓库
    └── jev-assistant-local-nanojev-release.apk   # 10 MB —— 不进仓库（走 Releases）
```

**桌面快捷入口**：`~/Desktop/启动Jev服务.command` —— 双击即启动服务并打印手机端地址。

---

## 四、快速开始

> ⚠️ **本机局域网地址会随网络变化**（路由器 DHCP 重新分配 / 有线无线切换，
> 实测同一天内变过两次）。**所以不要在任何地方写死地址。**
>
> 启动脚本与 APK 安装页（8899）都会打印**当前正确的**判断服务地址，
> 把它手动填进 App 的「本地 NanoJev 服务地址」即可。连不上时最可能的原因，
> 是手机与 Mac 不在同一个 WiFi。

### 0. 一步启动（推荐）

双击桌面上的 **`启动Jev服务.command`**。它会：

1. 检查服务是否已经在跑（在跑就直接告诉你地址，不重复启动）
2. 打印手机端要填的地址
3. 加载模型并开始服务

首次加载 2.22 GiB 权重转 fp16，**实测 160 秒**（一次性）；进程常驻后不再重复加载。

命令行等价写法：

```bash
cd nanojev
./run_server.sh
```

### 1. 把 APK 装到手机

**方式 A：手机浏览器直接下（推荐，不用线也不用微信）**

Mac 上另开一个终端跑：

```bash
cd nanojev
python3 serve_apk.py        # 用你本机的 Python 3（需已装好服务端依赖）
```

手机连**同一个 WiFi**，浏览器打开它打印的地址（形如 `http://192.168.x.x:8899`），
点页面上的按钮下载安装。

**方式 B：数据线**

```bash
adb install -r \
  jev-android/jev-assistant-local-nanojev-release.apk
```
（手机需先开「开发者选项 → USB 调试」）

### 2. 手机端配置

装完后打开 → **设置**：

1. 在 **「本地 NanoJev 服务地址」** 里填 Mac 的局域网地址（启动脚本会打印，形如
   `http://192.168.x.x:8788`）；手机与 Mac 需连同一个 WiFi
2. 点 **连通测试** → 看到 `[本地 NanoJev]` + 风险等级 即通

### 3. 权限（与原版一致，小米/HyperOS 必做）

无障碍、悬浮窗、自启动 + 省电无限制。无障碍服务就是「Jev助手」本身，
在系统设置里按应用名显示，进去把总开关打开即可。

---

## 五、实测数据（2026-09-22，本机 Apple M4 实测，非估算）

**环境**：MacBook-Air M4 / macOS 26.5.2 (arm64) · Python 3.13.12
· torch 2.14.0 · transformers 5.17.0 · safetensors 0.8.0

| 指标 | 数值 |
|---|---|
| 设备 / 精度 | `mps` / `float16`（权重以 fp32 存储，加载后转 fp16） |
| 权重体积 | 2,385,039,280 B（2.22 GiB）|
| SHA256 | `f68c47d66998231b86b7e91b4ed5e82ae23acf104c8b7cd6d165c3ac7b7ffe1b` |
| **首次加载权重** | **160.5 s**（一次性；之后常驻复用） |
| 题目数 | 8（7 判断 + 1 排序）|
| 候选路径数 | 34 |
| 预填 token 总数 | 8,413 |
| **服务端推理耗时** | **第 1 次 12.99 s / 稳定后 7.99 s**（MPS 预热效应）|
| 往返总耗时 | 13.01 s → 8.01 s |
| 3 题精简版耗时 | 0.95–1.70 s |
| 模型加载次数 | 1（常驻，不重复加载）|
| 输出确定性 | 确定性（同输入重复测逐位一致）|

**哈希校验基准**：以 HuggingFace 仓库 `SHA256_MANIFEST.json` 与 API 返回的
`lfs.oid` 为准（两者一致）。仓库 `research/` 目录下另有一个 `fff62d14…` 的哈希，
属于对照实验记录，**不是** `best.safetensors` 的哈希。

### 判断输出样例（中文聊天场景，app 真实请求形状）

```
literal_question   noul=0.843  conf=0.843
true_intent        choice=casual_chat  conf=0.252
                   （casual_chat=0.25, request_action=0.18, close_topic=0.17）
danger_level       score=4.42   conf=0.138  levels=10
should_reply_now   noul=0.860  conf=0.860
best_action        choice=apologize    conf=0.178
she_needs          choice=nothing      conf=0.326
tension_resolved   noul=0.857  conf=0.857
best_reply         choice=reply_c      conf=0.449
                   （reply_c=0.45, reply_a=0.32, reply_b=0.24）
```

→ 链路可用，但**多选类问题的概率分布接近平坦**（置信度 0.18–0.33），
见下节限制说明。

### APK 产物

| 变体 | 体积 | 签名 |
|---|---|---|
| debug | 12 MB | `CN=Android Debug` |
| release | 10 MB | `CN=Jev Assistant`（本地自签，10,950 天有效期）|

包名 `com.jev.probe`，应用名「Jev助手」，`minSdk 30` / `targetSdk 35`。

---

## 六、已知限制（重要）

### 1. 概率分布普遍偏平 —— 且**不是**「跨域」造成的

原先的判断是「低置信度源于训练域是游戏」。**实测推翻了这一解释**。
用同一套问题、两种状态做对照（`domain_probe.py`）：

| 题目 | 中文聊天状态（A） | 游戏状态（B，模型训练域） | 重复测（C） |
|---|---|---|---|
| `literal_question` (boolean) | p_true=0.7842 | p_true=0.7574 | 0.7842 |
| `best_action` (10 选 1) | apologize **0.196** | casual_reply **0.157** | 0.196 |
| `true_intent` (6 选 1) | answer **0.369** | answer **0.229** | 0.369 |

结论有两条：

- **领域不是主因。** 在迷宫导航（NanoJev 的主训练域）状态下，同一问题的置信度
  反而**更低**。偏平分布是模型与这套 10 选 / 6 选问题形式之间的固有特性。
- **A 与 C 完全一致**（逐位相同），说明推理是确定性的（`temperature=1.0`，无采样），
  反复调用不会给出漂移的结果。

**实际可用的用法是「相对排序」，不是「绝对置信度」。**
排序题（`best_reply`）给出 reply_c=0.45 / reply_a=0.32 / reply_b=0.24，
**序关系**是有信息量的；而 0.196 这种绝对值不应当作可信度来解读。

### 2. 其余限制

- **手机必须与 Mac 在同一 WiFi。** 出门在外用不了；此时可在设置页把地址清空，
  回落到云端 Jev（需 OpenRouter 密钥）。
- **回复起草仍需 OpenRouter 密钥。** NanoJev 只做判断，不生成文本。
- 原版 app 的其它限制照旧（国产 ROM 后台冻结、群聊按一对一处理、无障碍采集方式可能随聊天应用更新失效）。

---

## 七、改造点清单（安卓端）

| 文件 | 改动 |
|---|---|
| `core/Prefs.kt` | 新增 `localJevUrl` / `usesLocalJev` / `canAnalyze()` / `backendLabel()` |
| `jev/JevClient.kt` | 构造参数加 `localJevBase`；判断地址按配置切换；读超时放宽到 10 分钟；新增健康探测（3 秒）避免地址失效时白等；错误文案区分本地/云端 |
| `SettingsActivity.kt` | 新增「本地 NanoJev 服务地址」输入项及说明；连通测试支持本地模式 |
| `capture/ChatCaptureService.kt` | 判断前置条件从"必须有密钥"改为"有本地服务或有密钥" |
| `MainActivity.kt` | 就绪卡片改判 `canAnalyze()`，标签随后端显示 |
| `AndroidManifest.xml` | `usesCleartextTraffic="true"`（连局域网 HTTP 必需） |

**未改动**：题目集（`JevQuestions.kt`）、悬浮窗（`OverlayController.kt`）、
采集层（`capture/`）全部原样。

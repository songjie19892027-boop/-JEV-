# 上游与归属声明（NOTICE）

本仓库是 **Jev 聊天助手的 Android 端二次开发版**，在上游开源代码基础上增加了「本地 NanoJev 判断服务」方案与职场场景的判断题集。

## 一、上游

| 环节 | 项目 | 说明 |
|---|---|---|
| Android 主上游 | [jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis) | 本项目直接基于它改造 |
| macOS 上游 | [jev-chat/jev-chat-jarvis-mac](https://github.com/jev-chat/jev-chat-jarvis-mac) | 同系列，本仓库未包含 |
| 初始上游 | [jev-jarvis/jev-jarvis](https://github.com/jev-jarvis/jev-jarvis) | 最早的项目源头 |
| 本地判断模型 | [TianyuCodings/NanoJev](https://github.com/TianyuCodings/NanoJev) | `nanojev/` 目录所基于的开源判断模型，许可证见其仓库 |
| 判断模型基座 | [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) | 模型权重，许可证见其模型页 |

## 二、版权与许可证

- 上游作者版权：`Copyright (c) 2026 Finderchangchang and the jev-chat contributors`
- 上游许可证：**MIT**，完整原文原样保留在 [LICENSE](LICENSE)，未作任何修改。
- 本项目二次开发部分版权：`Copyright (c) 2026 <请填入你的姓名或 GitHub 账号>`

### 使用本项目时必须遵守（MIT + 上游 NOTICE 的要求）

1. **保留** `LICENSE` 与 `NOTICE`（本文件），不得删改版权声明；
2. 分发或商用时**注明出处**，推荐写法：
   > 基于 Jev 聊天助手（https://github.com/jev-chat/jev-chat-jarvis）二次开发
3. **不得**使用「Jev 聊天助手」「jev-chat」名称或官网域名，暗示由原作者出品或背书。

> ⚠️ 第 3 条对本仓库同样适用：本项目的 APK 名称、应用标题、仓库名如果继续沿用「Jev 聊天助手」，
> 建议改为自定名称（例如「对话副驾 · 本地判断版」），并在说明中写清"基于…二次开发"。

## 三、商标与非官方声明

- 「微信」「WeChat」等名称与商标归其各自权利人所有。本项目是**独立的第三方辅助工具**，与腾讯无任何关联，**不表示腾讯官方出品或授权**。
- 本项目不包含、不修改、不再分发任何聊天应用的代码、图标或数据。

## 四、本项目相对上游的主要改动

- 新增 `nanojev/`：把判断模型搬到本机 Mac，通过局域网 HTTP 服务给手机提供判断（`POST /api/alpha/decisions`）。
- 安卓端新增「本地 NanoJev 服务地址」配置与连通探测，判断后端可在「本地 / 云端」间切换。
- 判断题集从「生活/伴侣对话」场景改为**职场场景**（言语深意 / 推责 / 甩锅 / 派活 / 是否需留痕）。
- 新增关键词规则层 `jev/JevWorkRules.kt`：固定职场套话的本地匹配，可解释、可自行编辑、不依赖模型。
- 新增云端判断通道（DeepSeek 官方直连）。
- 保留上游的采集 → 判断 → 起草 → 排序 → 填入链路，**发送动作始终由用户自己完成**。

# 上游与归属声明（NOTICE）

本目录是 **Jev 聊天助手 Android 端**的二次开发版。

## 上游

- 直接上游：[jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis)
- 初始上游：[jev-jarvis/jev-jarvis](https://github.com/jev-jarvis/jev-jarvis)
- 上游作者版权：`Copyright (c) 2026 Finderchangchang and the jev-chat contributors`
- 上游许可证：**MIT**，原文原样保留在 [LICENSE](LICENSE)（未作任何修改）
- 本项目二次开发部分版权：`Copyright (c) 2026 <请填入你的姓名或 GitHub 账号>`

## 使用本项目必须遵守

1. **保留** `LICENSE` 与 `NOTICE`（本文件），不得删改版权声明；
2. 分发或商用时**注明出处**：「基于 Jev 聊天助手（https://github.com/jev-chat/jev-chat-jarvis）二次开发」；
3. **不得**使用「Jev 聊天助手」「jev-chat」名称或官网域名，暗示由原作者出品或背书。

> 因此本项目的 APK 文件名、应用标题、仓库名建议改用自定名称，不要直接沿用上游项目名。

## 商标与非官方声明

「微信」「WeChat」等名称与商标归其各自权利人所有。本项目是**独立第三方辅助工具**，
与腾讯无任何关联，**不表示腾讯官方出品或授权**。本项目不包含、不修改、不再分发任何聊天应用的代码或数据。

## 本目录相对上游的主要改动

- 判断后端可切换到本机 / 局域网的本地判断服务，并新增对应配置项与连通探测；
- 判断题集由「生活/伴侣对话」场景改为**职场场景**（言语深意 / 推责 / 甩锅 / 派活 / 是否需留痕）；
- 新增关键词规则层 `jev/JevWorkRules.kt`（本地词表匹配，可解释、可自行编辑、不依赖模型）；
- 新增云端判断通道（DeepSeek 官方直连）；
- 保留上游「采集 → 判断 → 起草 → 排序 → 填入」链路，**发送动作始终由用户自己完成**。

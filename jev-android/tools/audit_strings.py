#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEX 文案稽核：确认新版 APK 里该有的中文串在、该删的不在。

为什么不用 strings：
  DEX 里字符串是 MUTF-8（Modified UTF-8），`strings` 按 ASCII 找不出去中文，
  必须自己在字节流里做子串计数。

用法：
  python3 tools/audit_strings.py [APK 路径]
  默认取 app/build/outputs/apk/release/app-release.apk
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_APK = os.path.join(ROOT, "app/build/outputs/apk/release/app-release.apk")

# ---- 新版应存在（=1 或以上）----
MUST_EXIST = [
    "DeepSeek",
    "deepseek-chat",
    "api.deepseek.com",
    "判断模型",
    "备用通道的生成模型",
    "备用通道 · 不用填",
    "候选回复（按推荐度）",
    "都靠这一个密钥",
    "留痕",
    "疑似派活",
    "疑似推责",
    "暗中施压",
    "像是纯知会",
    "风险",
    "你看着办",
    "出了问题你负责",
    "不用回复",
    "辅助参考",
    # 按主因区分的风险定性措辞（改动 dangerWord 时同步这里）
    "有派活迹象",
    "活压得不轻",
    "归口没说清",
    "弦外之音",
    "话锋在往你这边引",
    "很可能背锅",
    # 2026-09-23 服务改用中性命名，DEX 类型描述符里应含这个类名
    "ChatCaptureService",
]

# ---- 旧版应清零（=0）----
MUST_BE_GONE = [
    "自动查找 Mac 服务",
    # 候选回复改走 DeepSeek 后，OpenRouter 从"生成用·可选"降为"备用通道·不用填"
    "OpenRouter 密钥（生成候选回复用 · 可选）",
    "回复生成模型",
    "候选回复（Jev 排序）",
    "只有生成面板底部那 3 条候选回复需要它",
    # 候选回复合并进 DeepSeek 后，这句仍在代码里（虽是注释性质，但会进 DEX）
    "要同时生成候选回复，还需再填 OpenRouter 密钥",
    "对方是你的伴侣",
    "感情",
    "暧昧",
    "撒娇",
    "是不是喜欢你",
    "危险",
]

# ---- 旧服务命名（APK 全包扫描，应 =0）----
# 2026-09-23 服务改用中性命名后新加：这些串只要出现在 APK 任何位置
# （DEX / AndroidManifest.xml / resources.arsc），都算发布阻断项。
GONE_ANYWHERE = [
    "selecttospeak",
    "SelectToSpeak",
    "config_disguised",
    "a11y_desc_disguised",
    "com.google.android.accessibility",
]


def dex_blob(apk: str) -> bytes:
    with zipfile.ZipFile(apk) as z:
        names = [n for n in z.namelist() if n.endswith(".dex")]
        names.sort()
        blob = b"".join(z.read(n) for n in names)
        print(f"DEX 文件：{', '.join(names)}  （合计 {len(blob)/1048576:.1f} MB）\n")
        return blob


def search_all(apk: str, needle: str) -> list:
    """在 APK 所有条目里找 needle，命中返回 [(条目名, 次数)]。

    文本条目按 UTF-8 与 UTF-16LE 各数一次：DEX 用 MUTF-8（ASCII 段与 UTF-8
    相同），而 AndroidManifest.xml / resources.arsc 的字符串池是 UTF-16LE。
    """
    nb_u8 = needle.encode("utf-8")
    nb_u16 = needle.encode("utf-16-le")
    hits = []
    with zipfile.ZipFile(apk) as z:
        for n in z.namelist():
            try:
                data = z.read(n)
            except Exception:
                continue
            c = data.count(nb_u8) + data.count(nb_u16)
            if c:
                hits.append((n, c))
    return hits


def main() -> int:
    apk = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_APK
    if not os.path.isfile(apk):
        print(f"找不到 APK：{apk}", file=sys.stderr)
        return 2
    print(f"APK：{apk}\n")
    blob = dex_blob(apk)

    bad = 0
    print("=== 新文案（应 >=1）===")
    for s in MUST_EXIST:
        n = blob.count(s.encode("utf-8"))
        mark = "OK " if n > 0 else "!! "
        if n == 0:
            bad += 1
        print(f"  {mark}{s:<28} {n}")

    print("\n=== 旧文案（应 =0）===")
    for s in MUST_BE_GONE:
        n = blob.count(s.encode("utf-8"))
        mark = "OK " if n == 0 else "!! "
        if n != 0:
            bad += 1
        print(f"  {mark}{s:<28} {n}")

    print("\n=== 旧服务命名（APK 全包，应 =0）===")
    for s in GONE_ANYWHERE:
        hits = search_all(apk, s)
        total = sum(c for _, c in hits)
        mark = "OK " if total == 0 else "!! "
        if total:
            bad += 1
        where = "" if not hits else "  ← " + ", ".join(f"{n}({c})" for n, c in hits[:4])
        print(f"  {mark}{s:<32} {total}{where}")

    print()
    if bad:
        print(f"稽核未通过：{bad} 项不符")
        return 1
    print("稽核通过：全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())

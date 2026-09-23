#!/usr/bin/env python3
"""盯住 NanoJev 服务，判断「手机的请求到底有没有到 Mac」。

比 watch_conn2.py 多一路关键信号：服务 /health 里的 `inference_calls` 计数器。
只要它增长，就说明**确实有人发起了一次完整分析**（不是探测、不是误报）。

三路信号：
  1. 入站 TCP 连接（来源 IP:端口 → 本机:端口，含 ESTABLISHED / SYN_RCVD / TIME_WAIT）
  2. 本机 en0 地址变化（换网络时立刻可见）
  3. inference_calls 增量（真实分析次数）

用法：watch_service.py [持续秒数]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

PORTS = ("8788", "8899")
HEALTH = "http://127.0.0.1:8788/health"


def local_ip() -> str:
    try:
        return subprocess.run(
            ["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


def health() -> dict | None:
    try:  # 本机回环不要走代理，否则可能拿到假阴性
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(HEALTH, timeout=4) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def conns() -> list[tuple[str, str, str]]:
    try:
        out = subprocess.run(
            ["netstat", "-an"], capture_output=True, text=True, timeout=6
        ).stdout
    except Exception:
        return []
    hits = []
    for line in out.splitlines():
        if "LISTEN" in line:
            continue
        for p in PORTS:
            if f".{p}" in line:
                f = line.split()
                if len(f) >= 6:
                    hits.append((f[3], f[4], f[5]))
                break
    return hits


def main() -> None:
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 1800

    ip0 = local_ip()
    h0 = health()
    calls0 = (h0 or {}).get("inference_calls", 0)
    print("[watch] 服务哨兵启动", flush=True)
    print(f"[watch] 本机地址：{ip0 or '（无）'}", flush=True)
    print(f"[watch] 服务状态：{'在线' if h0 else '❌ 连不上 → 双击桌面「启动Jev服务.command」'}", flush=True)
    print(f"[watch] 起始推理次数：{calls0}", flush=True)
    print(f"[watch] 持续 {dur}s，盯端口 {PORTS} …", flush=True)
    print("-" * 74, flush=True)

    seen: set[tuple[str, str, str]] = set()
    calls = calls0
    ip = ip0
    t0 = time.time()
    last_beat = 0.0

    while time.time() - t0 < dur:
        # --- 1. 地址变化 ---
        cur = local_ip()
        if cur and cur != ip:
            print(f"[+{int(time.time()-t0):4d}s] ★★★ 本机地址变化：{ip} → {cur}", flush=True)
            ip = cur
            if health():
                print(f"[+{int(time.time()-t0):4d}s]     新地址上的 8788：✅ 正常（服务绑 0.0.0.0，无需重启）", flush=True)

        # --- 2. 入站连接 ---
        for src, dst, st in conns():
            key = (src, dst, st)
            if key in seen:
                continue
            seen.add(key)
            remote = src.split(".")[0] not in ("127",)
            flag = "★ 入站连接" if remote else "· 本机连接"
            print(f"[+{int(time.time()-t0):4d}s] {flag}：{src} → {dst}  [{st}]", flush=True)

        # --- 3. 真实推理次数（最强信号）---
        h = health()
        if h:
            n = h.get("inference_calls", 0)
            if n > calls:
                print(f"[+{int(time.time()-t0):4d}s] ✅✅✅ 真实分析发生：推理次数 {calls} → {n}", flush=True)
                print(f"[+{int(time.time()-t0):4d}s]      设备={h.get('device')} 精度={h.get('dtype')}"
                      f" 权重={h.get('weights_bytes')}字节", flush=True)
                calls = n
        elif not h:
            pass

        # --- 心跳（每 5 分钟一次，说明还活着）---
        el = time.time() - t0
        if el - last_beat >= 300:
            last_beat = el
            print(f"[+{int(el):4d}s] …运行中（推理次数 {calls}，地址 {ip}）", flush=True)

        time.sleep(2)

    print("-" * 74, flush=True)
    print(f"[watch] 结束。推理次数：{calls0} → {calls}"
          f"（{'有真实分析 ✅' if calls > calls0 else '期间无分析'}）", flush=True)
    if calls > calls0:
        print("[watch] 结论：手机 → Mac 的完整链路已打通。", flush=True)
    else:
        print("[watch] 结论：期间没有真实分析请求到达。", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""监听 8788/8899 端口上的入站连接，判断「手机的包有没有到达 Mac」。

macOS 上没有 sudo 时 tcpdump 不可用，改用轮询 netstat：
LISTEN 行排除掉，其余非 LISTEN 条目（SYN_RCVD / ESTABLISHED / TIME_WAIT / CLOSE_WAIT）
就代表「有人连过这个端口」，来源 IP 一看便知。
"""
import re
import subprocess
import sys
import time

PORTS = ("8788", "8899")
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 900

SELF = {"192.168.1.10", "127.0.0.1", "::1", "*"}

# 只记录「首次见到」的组合，避免同一条连接被刷屏
seen = set()
start = time.time()
print(f"[watch] 开始监听端口 {PORTS}，持续 {DURATION}s，等待手机发起连接…", flush=True)
print("[watch] 请现在到手机 App 里点一次「连通测试」或「自动查找 Mac 服务」", flush=True)
print("-" * 72, flush=True)

while time.time() - start < DURATION:
    try:
        out = subprocess.run(
            ["netstat", "-an"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception as e:
        print(f"[watch] netstat 失败: {e}", flush=True)
        time.sleep(1)
        continue

    for line in out.splitlines():
        if not any(f".{p}" in line for p in PORTS):
            continue
        if "LISTEN" in line:
            continue
        # 形如：tcp4  0 0  192.168.1.10.8788  192.168.1.20.52341  ESTABLISHED
        parts = line.split()
        if len(parts) < 6:
            continue
        local, remote, state = parts[3], parts[4], parts[5]

        # 提取来源 IP
        m = re.match(r"(\d+\.\d+\.\d+\.\d+)\.(\d+)$", remote)
        if not m:
            continue
        rip, rport = m.group(1), m.group(2)
        if rip in SELF:
            continue

        key = (local.split(".")[-1], rip, state)
        if key in seen:
            continue
        seen.add(key)

        flag = "★ 疑似手机" if rip.startswith("192.168.1.") else "外部"
        elapsed = int(time.time() - start)
        print(
            f"[+{elapsed:>4}s] {flag}  来自 {rip}:{rport} → 本机 {local}  [{state}]",
            flush=True,
        )

    time.sleep(0.4)

print("-" * 72, flush=True)
if seen:
    print(f"[watch] 共捕获 {len(seen)} 个来源，结论：**有包到达 Mac**，网络层是通的。", flush=True)
else:
    print("[watch] 一个来源都没捕获到。", flush=True)
    print("[watch] 结论：**手机的包完全没有到达 Mac** → 属网络层问题，与 App 无关。", flush=True)

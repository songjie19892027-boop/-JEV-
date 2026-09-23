#!/usr/bin/env python3
"""增强版哨兵：同时监控「入站连接」与「本机 IP 变化」。

- 入站连接：轮询 netstat，排除 LISTEN，记录所有来源 IP
- IP 变化：每 2 秒比对 en0 地址，一变就打印（用户切 WiFi/热点时会立刻体现）

用途：用户按指引切换网络时，Mac 侧能否立刻看到新地址，以及手机有否连进来。
"""
import re
import subprocess
import sys
import time

PORTS = ("8788", "8899")
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
SELF_IPS = {"192.168.1.10", "127.0.0.1", "::1", "*"}


def get_ip() -> str:
    for iface in ("en0", "en1", "en2"):
        try:
            v = subprocess.run(
                ["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3
            ).stdout.strip()
            if v:
                return v
        except Exception:
            pass
    return ""


def get_iface(ip: str) -> str:
    for iface in ("en0", "en1", "en2"):
        try:
            v = subprocess.run(
                ["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3
            ).stdout.strip()
            if v == ip:
                return iface
        except Exception:
            pass
    return "?"


start = time.time()
cur_ip = get_ip()
SELF_IPS.add(cur_ip)

print("[watch] 端口监控 + IP 追踪启动", flush=True)
print(f"[watch] 起始地址：{cur_ip} ({get_iface(cur_ip)})    持续 {DURATION}s", flush=True)
print(f"[watch] 正在监听端口 {PORTS} …", flush=True)
print("-" * 74, flush=True)

seen = set()
last_ip_check = start

while time.time() - start < DURATION:
    now = time.time()
    elapsed = int(now - start)

    # ---- IP 变化（每 2 秒）----
    if now - last_ip_check > 2:
        last_ip_check = now
        new_ip = get_ip()
        if new_ip and new_ip != cur_ip:
            print(
                f"[+{elapsed:>4}s] ★★★ 本机地址变化：{cur_ip} → {new_ip}"
                f" ({get_iface(new_ip)})，说明网络已切换",
                flush=True,
            )
            cur_ip = new_ip
            SELF_IPS.add(new_ip)
            # 网络切换后，服务在新网卡上是否仍可达
            try:
                r = subprocess.run(
                    ["curl", "-s", "--noproxy", "*", "--max-time", "3",
                     f"http://{new_ip}:8788/health"],
                    capture_output=True, text=True, timeout=6,
                )
                ok = "ready" in r.stdout
                print(
                    f"[+{elapsed:>4}s]     新地址上的 8788 服务："
                    f"{'✅ 正常（无需重启服务）' if ok else '❌ 不可达，需重启服务'}",
                    flush=True,
                )
            except Exception:
                pass

    # ---- 入站连接 ----
    try:
        out = subprocess.run(
            ["netstat", "-an"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        time.sleep(1)
        continue

    for line in out.splitlines():
        if not any(f".{p}" in line for p in PORTS):
            continue
        if "LISTEN" in line:
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        local, remote, state = parts[3], parts[4], parts[5]
        m = re.match(r"(\d+\.\d+\.\d+\.\d+)\.(\d+)$", remote)
        if not m:
            continue
        rip, rport = m.group(1), m.group(2)
        if rip in SELF_IPS:
            continue

        key = (local.split(".")[-1], rip, state)
        if key in seen:
            continue
        seen.add(key)
        print(
            f"[+{elapsed:>4}s] ★ 入站连接：{rip}:{rport} → 本机 {local}  [{state}]",
            flush=True,
        )

    time.sleep(0.4)

print("-" * 74, flush=True)
print(f"[watch] 结束。捕获 {len(seen)} 个外部来源。", flush=True)
if seen:
    print("[watch] 结论：有设备成功连到 Mac，网络层是通的。", flush=True)
else:
    print("[watch] 结论：仍然零捕获 —— 没有任何设备的包到达 Mac。", flush=True)

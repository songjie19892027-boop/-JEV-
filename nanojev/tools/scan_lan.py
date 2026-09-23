#!/usr/bin/env python3
"""并发扫描本机所在 /24 网段，列出所有在线设备，并标注可疑的「手机特征」。

用途：判断手机到底在不在 Mac 所在的这个网段里。
"""
import ipaddress
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "192.168.2"


def ipconfig(iface):
    try:
        return subprocess.run(
            ["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3
        ).stdout.strip()
    except Exception:
        return ""


SELF = ipconfig("en0")


def ping(host, timeout_ms=300):
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_ms), "-n", host],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode == 0 and "bytes from" in r.stdout:
            m = re.search(r"time[=<]([\d.]+)\s*ms", r.stdout)
            rtt = m.group(1) if m else "?"
            return (host, rtt)
    except Exception:
        pass
    return None


def arp_table():
    """读 ARP 表，拿 MAC 地址（判断是否随机化 MAC / 厂商）。"""
    table = {}
    try:
        out = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            m = re.match(r"\?\s+\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-f:]+)", line)
            if m:
                table[m.group(1)] = m.group(2)
    except Exception:
        pass
    return table


def mac_kind(mac):
    """判断 MAC 类型：随机化（本地管理位=1）/ 固定。"""
    if not mac or mac == "(incomplete)":
        return "未知"
    first = mac.split(":")[0]
    try:
        b = int(first, 16)
    except ValueError:
        return "未知"
    locally_administered = bool(b & 0b10)
    multicast = bool(b & 0b01)
    if multicast:
        return "组播"
    return "★ 随机化(手机隐私地址)" if locally_administered else "固定厂商 MAC"


def main():
    net = ipaddress.ip_network(f"{PREFIX}.0/24", strict=False)
    hosts = [str(h) for h in net.hosts()]

    print(f"本机 en0 = {SELF or '未知'}    扫描范围 {PREFIX}.1 - {PREFIX}.254")
    print("正在并发探测（约 3 秒）…", flush=True)

    alive = []
    with ThreadPoolExecutor(max_workers=128) as pool:
        for res in pool.map(ping, hosts):
            if res:
                alive.append(res)

    alive.sort(key=lambda x: int(x[0].split(".")[-1]))
    arp = arp_table()

    print()
    print(f"{'IP':<18}{'RTT':<10}{'MAC':<22}类型")
    print("-" * 78)
    for host, rtt in alive:
        mac = arp.get(host, "(未在ARP)")
        mark = "  ← 本机" if host == SELF else ""
        print(f"{host:<18}{rtt + ' ms':<10}{mac:<22}{mac_kind(mac)}{mark}")

    print("-" * 78)
    print(f"在线设备：{len(alive)} 台")

    # 单独的 ARP 条目（本次没 ping 通，但 ARP 里有）
    extra = {k: v for k, v in arp.items() if k not in dict(alive) and k != SELF}
    if extra:
        print()
        print("ARP 表里有、但本次 ICMP 没响应（多为息屏的手机/休眠设备）：")
        for ip, mac in sorted(extra.items(), key=lambda kv: int(kv[0].split(".")[-1])):
            if ip.endswith(".255") or ip.endswith(".1"):
                continue
            print(f"  {ip:<18}{mac:<22}{mac_kind(mac)}")

    print()
    print("判读要点：")
    print("  · 手机在【在线设备】里 → 二层完全互通，问题在 App 侧")
    print("  · 手机只在【ARP 表】里 → 它在这个网段出现过，但当前休眠（正常）")
    print("  · 两处都没有手机 → 手机根本不在这个网段（连了别的 WiFi 或用流量）")


if __name__ == "__main__":
    main()

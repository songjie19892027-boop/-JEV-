#!/usr/bin/env python3
"""重启 NanoJev 决策服务，并把 stdout/stderr 落到 logs/server.log。

为什么要这个脚本
----------------
直接在 Bash 工具里 `nohup ... &` 起的进程，会在这一轮工具调用结束时被杀掉。
必须用 subprocess.Popen(start_new_session=True)（等价 setsid）才能真正脱离父进程
活到下一轮，所以这里做一次封装。

日志落盘的意义：jev_server.py 每次 HTTP 请求都会打一行
    [http] 2026-09-23 00:40:12 192.168.1.10 GET /health -> 200
带上客户端 IP 与时间。手机端一测，就能从日志直接判定
"到底有没有连上、连的是哪个地址"，不需要再挂 netstat / tcpdump 哨兵。

用法：python restart_server.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = Path(os.environ.get("NANOJEV_VENV", Path.home() / ".venvs" / "nanojev"))
CKPT = HERE / "checkpoints" / "NanoJev-unified"
LOG = HERE / "logs" / "server.log"
PORT = 8788


def listening_pids(port: int) -> list[int]:
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True,
    ).stdout
    return [int(x) for x in out.split() if x.strip().isdigit()]


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)

    for pid in listening_pids(PORT):
        print(f"[restart] 停止旧进程 PID={pid}", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    # 等端口释放
    for _ in range(30):
        if not listening_pids(PORT):
            break
        time.sleep(0.3)
    for pid in listening_pids(PORT):
        print(f"[restart] SIGTERM 未生效，强杀 PID={pid}", flush=True)
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.5)

    log_fh = open(LOG, "ab", buffering=0)
    log_fh.write(f"\n{'=' * 72}\n[restart] {time.strftime('%Y-%m-%d %H:%M:%S')} 启动新进程\n".encode())

    proc = subprocess.Popen(
        [
            str(VENV / "bin" / "python"), "-B",
            str(HERE / "server" / "jev_server.py"),
            "--checkpoint-dir", str(CKPT),
            "--host", "0.0.0.0",
            "--port", str(PORT),
            "--device", "auto",
        ],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=str(HERE),
        start_new_session=True,
    )
    print(f"[restart] 新进程 PID={proc.pid}，日志 -> {LOG}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

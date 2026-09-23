#!/usr/bin/env python3
"""重启 APK 分发页（8899）。

和 restart_server.py 同样的道理：必须 Popen(start_new_session=True) 才能跨轮次存活。
这个服务不加载模型，秒起。

用法：python restart_apk.py
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
LOG = HERE / "logs" / "apk_server.log"
PORT = 8899


def listening_pids(port: int) -> list[int]:
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True,
    ).stdout
    return [int(x) for x in out.split() if x.strip().isdigit()]


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)

    for pid in listening_pids(PORT):
        print(f"[apk] 停止旧进程 PID={pid}", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(30):
        if not listening_pids(PORT):
            break
        time.sleep(0.2)
    time.sleep(0.4)

    log_fh = open(LOG, "ab", buffering=0)
    log_fh.write(f"\n{'=' * 72}\n[apk] {time.strftime('%Y-%m-%d %H:%M:%S')} 启动新进程\n".encode())

    proc = subprocess.Popen(
        [str(VENV / "bin" / "python"), "-B", str(HERE / "serve_apk.py"),
         "--host", "0.0.0.0", "--port", str(PORT)],
        stdout=log_fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        cwd=str(HERE), start_new_session=True,
    )
    print(f"[apk] 新进程 PID={proc.pid}，日志 -> {LOG}", flush=True)
    time.sleep(1.2)
    code = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "-o", os.devnull, "-w", "%{http_code}",
         "-m", "4", f"http://127.0.0.1:{PORT}/"],
        capture_output=True, text=True,
    ).stdout.strip()
    print(f"[apk] 自检 http://127.0.0.1:{PORT}/ -> HTTP {code}", flush=True)
    return 0 if code == "200" else 1


if __name__ == "__main__":
    sys.exit(main())

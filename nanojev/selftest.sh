#!/bin/bash
# 自检：起服务 → 等就绪 → 用 app 真实请求形状打一次 → 收工
#
# 与服务分开跑在 127.0.0.1:8799，不影响 run_server.sh 的 8788。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${NANOJEV_VENV:-$HOME/.venvs/nanojev}"
CKPT="$HERE/checkpoints/NanoJev-unified"
PORT="${PORT:-8799}"
DEVICE="${1:-auto}"
DTYPE="${2:-auto}"
LOG="$HERE/_selftest_server.log"

echo "==================== 1/3 启动服务 ===================="
echo "设备=$DEVICE  精度=$DTYPE  端口=$PORT"
"$VENV/bin/python" "$HERE/server/jev_server.py" \
  --checkpoint-dir "$CKPT" --host 127.0.0.1 --port "$PORT" \
  --device "$DEVICE" --dtype "$DTYPE" > "$LOG" 2>&1 &
SRV=$!

cleanup() { kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; }
trap cleanup EXIT

echo "==================== 2/3 等待就绪 ===================="
READY=0
for i in $(seq 1 180); do
  if ! kill -0 "$SRV" 2>/dev/null; then
    echo "服务进程已退出，日志如下："
    tail -40 "$LOG"
    exit 1
  fi
  # 本机访问必须带 --noproxy '*'，否则代理会返回假失败
  if curl -s --noproxy '*' --max-time 3 "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
    READY=1
    echo "服务就绪（用时约 ${i}s）"
    curl -s --noproxy '*' "http://127.0.0.1:$PORT/health" | "$VENV/bin/python" -m json.tool
    break
  fi
  sleep 1
done

if [ "$READY" != "1" ]; then
  echo "180 秒内未就绪，日志："
  tail -40 "$LOG"
  exit 1
fi

if grep -qiE "error|traceback|exception" "$LOG"; then
  echo
  echo "⚠️ 启动日志里出现异常字样，请检查："
  grep -inE "error|traceback|exception" "$LOG" | head -20
fi

echo
echo "==================== 3/3 端到端推理测试 ===================="
"$VENV/bin/python" "$HERE/verify_local.py" \
  --url "http://127.0.0.1:$PORT/api/alpha/decisions" \
  --timeout 2400
RC=$?

echo
echo "==================== 服务端日志尾部 ===================="
tail -12 "$LOG"

exit $RC

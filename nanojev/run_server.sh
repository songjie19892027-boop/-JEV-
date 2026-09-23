#!/bin/bash
# 启动 NanoJev 本地决策服务（Mac 端）
#
# 用法：
#   ./run_server.sh            # MPS 优先（推荐）
#   ./run_server.sh cpu        # 强制 CPU（数值最保守，慢）
#
# 启动后手机端设置里把「本地 NanoJev 服务地址」填成本脚本打印的地址。

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${NANOJEV_VENV:-$HOME/.venvs/nanojev}"
CKPT="$HERE/checkpoints/NanoJev-unified"
DEVICE="${1:-auto}"
PORT="${PORT:-8788}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "找不到 Python 环境：$VENV/bin/python" >&2
  echo "请先创建 venv 并安装 torch / transformers / safetensors。" >&2
  exit 1
fi

if [ ! -f "$CKPT/best.safetensors" ]; then
  echo "找不到模型权重：$CKPT/best.safetensors" >&2
  exit 1
fi

# 打印本机局域网地址，手机要连的就是它
echo "=== 本机局域网地址（手机端填这个） ==="
for i in $(ifconfig 2>/dev/null | grep -E '^[a-z]' | cut -d: -f1); do
  ip=$(ipconfig getifaddr "$i" 2>/dev/null || true)
  if [ -n "${ip:-}" ]; then
    echo "  $i : http://$ip:$PORT"
  fi
done
echo

exec "$VENV/bin/python" "$HERE/server/jev_server.py" \
  --checkpoint-dir "$CKPT" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --device "$DEVICE"

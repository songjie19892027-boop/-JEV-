#!/bin/bash
# 构建 Jev 聊天助手 APK（含本地 NanoJev 支持）
#
# 产物：app/build/outputs/apk/debug/app-debug.apk
# 副本：./jev-assistant-local-nanojev-debug.apk
#
# 环境（工具链位置因机器而异，不写死）：
#   JDK 17 : 取 $JAVA_HOME；未设置时回退到 $HOME/android-dev/toolchain/<jdk 目录>
#   SDK    : 取 $ANDROID_HOME；未设置时回退到 $HOME/android-dev/sdk

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# 优先取环境变量；未设置时回退到本机默认位置。换机器请 export 覆盖。
export JAVA_HOME="${JAVA_HOME:-$HOME/android-dev/toolchain/jdk-17.0.20.1+1/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-dev/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

if [ ! -x "$JAVA_HOME/bin/java" ]; then
  echo "找不到 JDK：JAVA_HOME=$JAVA_HOME" >&2
  echo "请先 export JAVA_HOME=<你的 JDK 17 目录>" >&2
  exit 1
fi
if [ ! -d "$ANDROID_HOME" ]; then
  echo "找不到 Android SDK：ANDROID_HOME=$ANDROID_HOME" >&2
  echo "请先 export ANDROID_HOME=<你的 Android SDK 目录>" >&2
  exit 1
fi

echo "JDK : $("$JAVA_HOME/bin/java" -version 2>&1 | head -1)"
echo "SDK : $ANDROID_HOME"
echo

cd "$HERE"
ARGS="${*:-assembleDebug}"
./gradlew $ARGS

# 按构建类型输出不同文件名，避免 debug / release 互相覆盖
case "$ARGS" in
  *Release*) VARIANT="release"; APK="$HERE/app/build/outputs/apk/release/app-release.apk" ;;
  *)         VARIANT="debug";   APK="$HERE/app/build/outputs/apk/debug/app-debug.apk" ;;
esac

if [ -f "$APK" ]; then
  OUT="$HERE/jev-assistant-local-nanojev-$VARIANT.apk"
  cp "$APK" "$OUT"
  echo
  # 注意：变量后紧跟全角字符时必须用 ${} 包起来，
  # 否则 bash 会把全角括号当成变量名的一部分（报 unbound variable）
  echo "=== 构建成功（${VARIANT}） ==="
  echo "APK : $OUT"
  ls -lh "$OUT"
  echo
  echo "安装：adb install -r \"$OUT\""
fi

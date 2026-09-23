#!/usr/bin/env python3
"""生成「手机扫这个」自检页，二维码内联，含当前 Mac 的真实 IP。"""
import base64
import io
import subprocess
import sys

import segno

# ---------- 取当前局域网 IP ----------
IP = ""
for iface in ("en0", "en1", "en2"):
    try:
        v = subprocess.run(
            ["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3
        ).stdout.strip()
        if v:
            IP = v
            break
    except Exception:
        pass

if not IP:
    print("未取到局域网 IP，退出")
    sys.exit(1)

SUBNET = ".".join(IP.split(".")[:3]) + ".x"

# ① 指向 8899 的中文自检页（它会自己去 fetch 8788/health 并给出结论），
#    比直接打开 8788/health 的一屏 JSON 对使用者友好得多。
JUDGE = f"http://{IP}:8899/check"
INSTALL = f"http://{IP}:8899"


def qr_svg(data: str, scale: int = 5, dark: str = "#111827") -> str:
    q = segno.make(data, error="m")
    buf = io.BytesIO()
    q.save(buf, kind="svg", scale=scale, dark=dark, xmldecl=False, svgns=True)
    s = buf.getvalue().decode("utf-8")
    # 去掉固定宽高，交给 CSS 控制，便于响应式
    s = s.replace("<svg ", '<svg class="qrsvg" ', 1)
    return s


HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>手机扫这个 · 检测连接</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px 16px 60px; background:#f6f7f9; color:#111827;
    font:16px/1.65 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif; }}
  .wrap {{ max-width:720px; margin:0 auto; }}
  h1 {{ font-size:23px; margin:0 0 6px; letter-spacing:-.2px; }}
  .sub {{ color:#6b7280; font-size:14px; margin:0 0 22px; }}
  .ipbar {{ background:#111827; color:#fff; border-radius:14px; padding:16px 18px;
    margin-bottom:22px; }}
  .ipbar .k {{ font-size:13px; color:#9ca3af; }}
  .ipbar .v {{ font-size:26px; font-weight:700; font-family:ui-monospace,Menlo,monospace;
    letter-spacing:-.5px; margin-top:2px; word-break:break-all; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:22px;
    margin-bottom:16px; }}
  .card h2 {{ font-size:17px; margin:0 0 4px; }}
  .card .hint {{ font-size:13.5px; color:#6b7280; margin:0 0 16px; }}
  .qrbox {{ display:flex; justify-content:center; padding:14px; background:#fff;
    border:1px dashed #d1d5db; border-radius:12px; }}
  .qrsvg {{ width:230px; height:230px; display:block; }}
  code {{ background:#f3f4f6; padding:2px 7px; border-radius:5px; font-size:13.5px;
    font-family:ui-monospace,Menlo,monospace; word-break:break-all; }}
  .big {{ display:block; text-align:center; margin-top:14px; font-size:15px;
    font-weight:600; font-family:ui-monospace,Menlo,monospace; color:#1d4ed8;
    text-decoration:none; word-break:break-all; }}
  .big:hover {{ text-decoration:underline; }}
  .ok {{ color:#059669; font-weight:600; }}
  .no {{ color:#dc2626; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-size:14.5px; }}
  th, td {{ text-align:left; padding:11px 10px; border-bottom:1px solid #f0f1f3;
    vertical-align:top; }}
  th {{ color:#6b7280; font-weight:600; font-size:13px; }}
  tr:last-child td {{ border-bottom:none; }}
  .warn {{ background:#fff7e6; border:1px solid #fde68a; border-radius:14px;
    padding:18px 20px; margin-top:8px; }}
  .warn h2 {{ font-size:17px; margin:0 0 12px; color:#92400e; }}
  ol {{ padding-left:22px; margin:0; }}
  ol li {{ margin-bottom:10px; }}
  .step {{ display:inline-block; width:22px; height:22px; line-height:22px;
    background:#111827; color:#fff; border-radius:50%; text-align:center;
    font-size:13px; font-weight:700; margin-right:7px; }}
  .foot {{ text-align:center; color:#9ca3af; font-size:13px; margin-top:26px; }}
</style>
</head>
<body>
<div class="wrap">

  <h1>手机扫这个，10 秒测出卡在哪</h1>
  <p class="sub">Mac 现在是好的，服务也在跑。扫下面二维码，结果直接告诉你是「网络不通」还是「App 的问题」。</p>

  <div class="ipbar">
    <div class="k">Mac 当前地址（两个二维码都指向它）</div>
    <div class="v">{IP}</div>
  </div>

  <div class="card">
    <h2>① 先扫这个：自动测手机能不能连上 Mac</h2>
    <p class="hint">手机浏览器打开后，页面会自己跑测试，<b>直接给中文结论</b>，
      不用你自己看参数。</p>
    <div class="qrbox">{qr_svg(JUDGE)}</div>
    <a class="big" href="{JUDGE}">{JUDGE}</a>
    <table style="margin-top:18px">
      <tr><th style="width:46%">页面显示</th><th>说明</th></tr>
      <tr>
        <td><span class="ok">✅ 连接成功，网络完全通</span></td>
        <td><b>网络没问题！</b>剩下只可能是 App 本身 ——<br>
            扫 ② 装 App，设置页点「自动查找 Mac 服务」+「连通测试」</td>
      </tr>
      <tr>
        <td><span class="no">❌ 连不上 Mac（超时 8 秒）</span></td>
        <td><b>手机的请求没到达 Mac。</b>多半是手机走了移动数据，<br>
            或两边不在同一个 WiFi —— 按页面里的三步做</td>
      </tr>
      <tr>
        <td><span class="no">❌ 服务在，但没准备好</span></td>
        <td>网络是通的，只是 Mac 刚重启服务还在加载模型，<br>等 1 分钟刷新本页</td>
      </tr>
    </table>
  </div>

  <div class="card">
    <h2>② 再扫这个：装最新版 App</h2>
    <p class="hint">先扫 ① 能打开，这个才能打开。页面里点按钮直接下载安装。</p>
    <div class="qrbox">{qr_svg(INSTALL)}</div>
    <a class="big" href="{INSTALL}">{INSTALL}</a>
  </div>

  <div class="warn">
    <h2>如果 ① 号扫不开 —— 按顺序做这三步</h2>
    <ol>
      <li><span class="step">1</span><b>关掉手机的「移动数据」</b>，只留 Wi-Fi。<br>
          <span style="font-size:13.5px;color:#78716c">Android 在 Wi-Fi 信号弱时会偷偷改用流量，导致局域网请求发不出去。</span></li>
      <li><span class="step">2</span><b>看 Mac 连的是哪个 Wi-Fi。</b><br>
          点 Mac 屏幕右上角的 Wi-Fi 图标，最上面打勾的那个名字就是。<br>
          <span style="font-size:13.5px;color:#78716c">手机必须连<b>完全同名</b>的那个。附近有 15 个 Wi-Fi，名字很像但不是同一个的情况很常见。</span></li>
      <li><span class="step">3</span><b>在手机上核对 IP。</b><br>
          手机「设置 → WLAN → 点当前网络」，看 IP 是不是 <code>{SUBNET}</code>。<br>
          <span style="font-size:13.5px;color:#78716c">
            是 → 同网段，把自检页的结论告诉我；<br>
            不是 → 手机连的就是另一个网，换成和 Mac 同名的那个 WiFi。</span></li>
    </ol>
  </div>

  <p class="foot">Jev 助手 · 本地判断服务自检页</p>
</div>
</body>
</html>
"""

out = "手机扫这个-检测连接.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"已生成：{out}")
print(f"  IP      = {IP}")
print(f"  ① 测连通 = {JUDGE}")
print(f"  ② 装 App = {INSTALL}")

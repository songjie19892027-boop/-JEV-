#!/usr/bin/env python3
"""APK 局域网分发页 —— 手机浏览器打开就能下载安装。

用途：不想插数据线、也不想用微信传文件时，让手机连同一个 WiFi，
      浏览器访问本页，点一下就把 APK 装到手机上。

用法：
    python serve_apk.py            # 默认 8899 端口
    python serve_apk.py --port 9000
"""
from __future__ import annotations

import argparse
import html
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APK_DIR = Path(__file__).resolve().parent.parent / "jev-android"
APKS = [
    ("jev-assistant-local-nanojev-release.apk", "推荐 · release 签名版", "约 10 MB"),
    ("jev-assistant-local-nanojev-debug.apk", "备用 · debug 版", "约 12 MB"),
]


def lan_ips() -> list[tuple[str, str]]:
    out = []
    for iface in ("en0", "en1", "en2", "en3"):
        try:
            ip = subprocess.run(
                ["ipconfig", "getifaddr", iface],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip()
        except Exception:
            ip = ""
        if ip:
            out.append((iface, ip))
    return out


def build_page(port: int, jev_host: str = "") -> bytes:
    """jev_host: 手机访问本页时用的那台主机地址（从 Host 头取），
    用它拼出的 8788 地址一定就是手机能访问到的地址。"""
    ips = lan_ips()
    rows = []
    for name, label, size in APKS:
        path = APK_DIR / name
        if not path.exists():
            continue
        rows.append(
            '<a class="card" href="/dl/{n}">'
            '<span class="t">{l}</span>'
            '<span class="m">{n}<br>{s}</span>'
            '<span class="go">下载 →</span></a>'.format(
                n=html.escape(name), l=html.escape(label), s=html.escape(size)
            )
        )
    addr = ", ".join(f"http://{ip}:{port}" for _, ip in ips) or "（未检测到局域网地址）"

    # 判断服务地址：优先用手机实际能访问到的主机名，其次回退到本机网卡地址
    mine = jev_host if jev_host and not jev_host.startswith("127.") else (
        ips[0][1] if ips else "")
    jev_addr = f"http://{mine}:8788" if mine else "（未检测到，请先在 Mac 上启动服务）"
    health_link = (
        f'<a class="test" href="http://{html.escape(mine)}:{port}/check">'
        f'一键自检：测手机能不能连上 Mac →</a>' if mine else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>安装 Jev 助手</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
         margin:0; padding:24px 18px 60px; background:#f5f6f8; color:#1c1f24;
         -webkit-text-size-adjust:100%; }}
  h1 {{ font-size:21px; margin:0 0 6px; }}
  .sub {{ color:#6b7280; font-size:14px; margin:0 0 22px; line-height:1.6; }}
  .card {{ display:flex; align-items:center; gap:14px; background:#fff;
           border:1px solid #e3e6ea; border-radius:14px; padding:16px 18px;
           margin-bottom:12px; text-decoration:none; color:inherit; }}
  .card:active {{ background:#eef1f5; }}
  .t {{ font-weight:600; font-size:15px; flex:1; }}
  .m {{ display:none; }}
  .go {{ color:#0a66ff; font-size:14px; font-weight:600; white-space:nowrap; }}
  .note {{ background:#fff7e6; border:1px solid #ffe0a3; border-radius:12px;
           padding:14px 16px; font-size:13.5px; line-height:1.75; color:#7a5200; }}
  .note b {{ color:#5c3d00; }}
  .addr {{ background:#eaf1ff; border:1px solid #bcd2ff; border-radius:12px;
           padding:14px 16px; margin-bottom:14px; font-size:13.5px; color:#123a86; }}
  .addr .k {{ font-size:12px; color:#4a6fa8; margin-bottom:4px; }}
  .addr .v {{ font-family:"SF Mono",Menlo,Consolas,monospace; font-size:14.5px;
              font-weight:700; word-break:break-all; }}
  .test {{ display:inline-block; margin-top:9px; color:#0a66ff; font-weight:600;
           text-decoration:none; font-size:13.5px; }}
  code {{ background:#eef1f5; padding:1px 6px; border-radius:5px; font-size:13px; }}
  ol {{ padding-left:20px; margin:8px 0 0; }}
  li {{ margin-bottom:6px; }}
</style></head><body>
<h1>安装「Jev助手」</h1>
<p class="sub">同一个 WiFi 下，点下面的按钮就能下载安装。<br>本页地址：{html.escape(addr)}</p>
<div class="addr">
  <div class="k">Mac 判断服务地址（App 里要填的就是它）</div>
  <div class="v">{html.escape(jev_addr)}</div>
  {health_link}
</div>
{''.join(rows) or '<p class="sub">⚠️ 没有找到 APK 文件，请先执行构建。</p>'}
<div class="note">
  <b>装完还要做 4 件事（缺一不可）</b>
  <ol>
    <li>打开「Jev助手」→ <b>设置</b> → 点 <b>「自动查找 Mac 服务」</b>，
        它会自己扫出上面这个地址并填好<br>
        <span style="color:#8a6a20">（只有自动查找失败时，才需要手填「本地 NanoJev 服务地址」）</span></li>
    <li>点 <b>连通测试</b>，看到「[本地 NanoJev]」+ 危险等级 就算通了</li>
    <li>去系统设置里给它开 <b>无障碍</b>（列表里显示为
        「Jev助手」）、<b>悬浮窗</b>、<b>自启动</b>、
        <b>省电无限制</b></li>
    <li>手机浏览器下载 APK 后，系统可能提示「未知来源」——允许一次即可</li>
  </ol>
</div>
</body></html>""".encode("utf-8")


CHECK_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>连接自检 · Jev 助手</title>
<style>
  *{box-sizing:border-box;}
  body{margin:0;padding:22px 16px 56px;background:#f5f6f8;color:#1c1f24;
    font:16px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    -webkit-text-size-adjust:100%;}
  .wrap{max-width:560px;margin:0 auto;}
  h1{font-size:20px;margin:0 0 4px;}
  .sub{color:#6b7280;font-size:13.5px;margin:0 0 18px;}
  .box{background:#fff;border:1px solid #e3e6ea;border-radius:16px;padding:20px;
    margin-bottom:16px;}
  .badge{display:flex;align-items:center;gap:12px;font-size:19px;font-weight:700;}
  .dot{width:34px;height:34px;border-radius:50%;flex:0 0 34px;display:flex;
    align-items:center;justify-content:center;font-size:19px;color:#fff;}
  .run .dot{background:#f59e0b;} .run{color:#b45309;}
  .ok  .dot{background:#10b981;} .ok {color:#047857;}
  .bad .dot{background:#ef4444;} .bad{color:#b91c1c;}
  .msg{margin-top:14px;font-size:14.5px;line-height:1.75;}
  table{width:100%;border-collapse:collapse;font-size:14px;margin-top:14px;}
  td{padding:8px 0;border-bottom:1px solid #f0f1f3;vertical-align:top;}
  tr:last-child td{border-bottom:none;}
  td.k{color:#6b7280;width:42%;}
  td.v{font-family:ui-monospace,Menlo,Consolas,monospace;word-break:break-all;
    font-weight:600;}
  .hint{background:#fff7e6;border:1px solid #fde68a;border-radius:12px;
    padding:14px 16px;font-size:13.5px;line-height:1.8;color:#7a5200;margin-top:14px;}
  .hint b{color:#5c3d00;}
  ol{padding-left:20px;margin:8px 0 0;}
  li{margin-bottom:7px;}
  code{background:#eef1f5;padding:1px 6px;border-radius:5px;
    font-family:ui-monospace,Menlo,monospace;font-size:13px;}
  .btn{display:block;text-align:center;background:#111827;color:#fff;
    border-radius:12px;padding:13px;font-weight:600;text-decoration:none;
    font-size:15px;}
  .foot{text-align:center;color:#9ca3af;font-size:12.5px;margin-top:22px;}
  .raw{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#4b5563;
    word-break:break-all;margin-top:10px;}
</style></head><body>
<div class="wrap">
  <h1>连接自检</h1>
  <p class="sub">这个页面在手机上打开，就说明「手机 → Mac 的 8899 端口」已经通了。
     下面继续测「Mac 的 8788 判断服务」。</p>

  <div class="box">
    <div class="badge run" id="badge"><span class="dot" id="dot">…</span>
      <span id="title">正在测试…</span></div>
    <div class="msg" id="msg">请保持手机和 Mac 在同一个 WiFi，最多等 8 秒。</div>
    <table id="detail" style="display:none">
      <tr><td class="k">手机自己的 IP</td><td class="v" id="d-phone">-</td></tr>
      <tr><td class="k">Mac 服务地址</td><td class="v" id="d-url">-</td></tr>
      <tr><td class="k">推理设备</td><td class="v" id="d-dev">-</td></tr>
      <tr><td class="k">已处理分析次数</td><td class="v" id="d-calls">-</td></tr>
    </table>
    <div class="hint" id="hint" style="display:none"></div>
  </div>

  <div class="box" id="nextbox" style="display:none">
    <a class="btn" href="/">下一步：下载安装 App →</a>
  </div>

  <div class="box">
    <div style="font-size:14px;font-weight:600;margin-bottom:6px">测不通怎么办</div>
    <ol>
      <li>关掉手机的<b>移动数据</b>，只留 WiFi。Android 在 WiFi 弱时会偷偷改用流量，
          局域网请求就发不出去。</li>
      <li>回桌面双击 <code>启动Jev服务.command</code>，确认 Mac 上服务在跑
          （它会打印地址；已在跑会提示）。</li>
      <li>确认手机上显示的 WiFi 名字和 Mac 连的<b>完全同名</b>。</li>
      <li>把本页顶部这行红字和「手机自己的 IP」念给我，我就能定位。</li>
    </ol>
  </div>

  <p class="foot">Jev 助手 · 连接自检页</p>
</div>
<script>
(function () {
  var host = location.hostname;
  var url = 'http://' + host + ':8788/health';
  var badge = document.getElementById('badge');
  var dot = document.getElementById('dot');
  var title = document.getElementById('title');
  var msg = document.getElementById('msg');
  var hint = document.getElementById('hint');
  var detail = document.getElementById('detail');
  var dUrl = document.getElementById('d-url');
  dUrl.textContent = url;

  function finish(cls, sym, t, m) {
    badge.className = 'badge ' + cls;
    dot.textContent = sym;
    title.textContent = t;
    msg.innerHTML = m;
  }

  var ctrl = new AbortController();
  var timer = setTimeout(function () { ctrl.abort(); }, 8000);

  fetch(url, {cache: 'no-store', signal: ctrl.signal}).then(function (r) {
    clearTimeout(timer);
    return r.json();
  }).then(function (j) {
    if (!j || j.ready !== true) {
      finish('bad', '!', '服务在，但没准备好',
        'Mac 上的判断服务还没加载完模型，等 1 分钟再点一次本页刷新。');
      return;
    }
    finish('ok', '✓', '连接成功，网络完全通',
      '手机能直接访问 Mac 的判断服务。剩下的问题只可能在 App 里，不在网络上。');
    document.getElementById('d-phone').textContent = j.your_ip || '-';
    document.getElementById('d-dev').textContent = j.device || '-';
    document.getElementById('d-calls').textContent = j.inference_calls;
    detail.style.display = '';
    hint.style.display = '';
    hint.innerHTML = '<b>下一步：</b>装 App 后去设置页点「自动查找 Mac 服务」'
      + '再点「连通测试」。本页能通，App 里就一定能通。';
    document.getElementById('nextbox').style.display = '';
  }).catch(function (e) {
    clearTimeout(timer);
    var aborted = (e && e.name === 'AbortError');
    if (aborted) {
      finish('bad', '×', '连不上 Mac（超时 8 秒）',
        '手机的请求根本没到达 Mac。最常见的原因是手机这会儿走了<b>移动数据</b>，'
        + '或者两边不在同一个 WiFi。');
    } else {
      finish('bad', '×', '连不上 Mac',
        '网络层就失败，说明手机到 Mac 的 <b>8788 端口</b>不通（服务停了，或不在同一网段）。');
    }
    hint.style.display = '';
    hint.innerHTML = '<b>请按顺序做：</b><ol>'
      + '<li>关掉手机「移动数据」，只留 WiFi，刷新本页重试。</li>'
      + '<li>在 Mac 上双击 <code>启动Jev服务.command</code>，看它是否提示服务已在运行。</li>'
      + '<li>核对手机 WiFi 名称与 Mac 完全一致。</li></ol>';
    detail.style.display = '';
    document.getElementById('d-phone').textContent =
      '（测不通，取不到）请到手机「设置 → WLAN → 当前网络」里看';
  });
})();
</script>
</body></html>"""


def build_check_page() -> str:
    """手机端一键自检页：由页面自己去 fetch Mac 的 8788/health，
    用中文直接给出「通 / 不通」和下一步。"""
    return CHECK_PAGE_HTML


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        port = self.server.server_address[1]
        if self.path in ("/", "/index.html"):
            # 用手机实际访问的主机地址来拼 8788 地址 —— 它必然是手机能访问到的那个
            host_hdr = (self.headers.get("Host") or "").split(":")[0].strip()
            body = build_page(port, host_hdr)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.split("?")[0] in ("/check", "/check.html"):
            body = build_check_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/dl/"):
            name = self.path[4:].split("?")[0]
            # 防目录穿越：只允许白名单里的文件名
            if name not in {n for n, _, _ in APKS}:
                self.send_error(404)
                return
            path = APK_DIR / name
            if not path.exists():
                self.send_error(404)
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type",
                             "application/vnd.android.package-archive")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with path.open("rb") as fh:
                while True:
                    buf = fh.read(1 << 20)
                    if not buf:
                        break
                    self.wfile.write(buf)
            return

        self.send_error(404)

    def log_message(self, fmt, *args):
        print(f"[apk] {fmt % args}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    print("=" * 58)
    print("  APK 分发页已启动。手机浏览器打开下面任意一个地址：")
    for iface, ip in lan_ips():
        print(f"    http://{ip}:{args.port}          ({iface})")
    print("=" * 58, flush=True)

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

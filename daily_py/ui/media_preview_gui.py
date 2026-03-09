"""在线媒体预览工具 — 输入图片/视频链接，直接预览播放。

使用浏览器渲染，无需下载文件到本地。

Usage::

    python -m daily_py.ui.media_preview_gui
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# 内嵌 HTML 页面
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>DailyPy - Media Preview</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
         background: #1a1a2e; color: #e0e0e0; min-height: 100vh;
         display: flex; flex-direction: column; align-items: center; padding: 20px; }
  h1 { font-size: 20px; margin-bottom: 16px; color: #a0c4ff; }
  .input-row { display: flex; gap: 8px; width: 90%; max-width: 900px; margin-bottom: 16px; }
  input[type=text] { flex: 1; padding: 10px 14px; border: 1px solid #444; border-radius: 6px;
                     background: #16213e; color: #e0e0e0; font-size: 14px; outline: none; }
  input[type=text]:focus { border-color: #a0c4ff; }
  button { padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer;
           font-size: 14px; font-weight: 600; transition: background .2s; }
  .btn-primary { background: #0f3460; color: #fff; }
  .btn-primary:hover { background: #1a4a8a; }
  .btn-clear { background: #533483; color: #fff; }
  .btn-clear:hover { background: #6e44a0; }
  .preview-area { width: 90%; max-width: 900px; min-height: 300px;
                  background: #16213e; border-radius: 8px; display: flex;
                  align-items: center; justify-content: center; overflow: hidden;
                  border: 1px solid #333; }
  .preview-area img { max-width: 100%; max-height: 80vh; object-fit: contain; }
  .preview-area video { max-width: 100%; max-height: 80vh; }
  .placeholder { color: #555; font-size: 16px; }
  .history { width: 90%; max-width: 900px; margin-top: 16px; }
  .history summary { cursor: pointer; color: #888; font-size: 13px; }
  .history ul { list-style: none; padding: 8px 0; max-height: 200px; overflow-y: auto; }
  .history li { padding: 4px 0; font-size: 13px; cursor: pointer; color: #7799bb;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .history li:hover { color: #a0c4ff; text-decoration: underline; }
</style>
</head>
<body>
  <h1>Media Preview</h1>
  <div class="input-row">
    <input id="url" type="text" placeholder="输入图片或视频链接…" autofocus />
    <button class="btn-primary" onclick="preview()">预览</button>
    <button class="btn-clear" onclick="clearAll()">清空</button>
  </div>
  <div class="preview-area" id="preview">
    <span class="placeholder">粘贴链接后点击「预览」</span>
  </div>
  <details class="history" id="historySection" style="display:none">
    <summary>历史记录</summary>
    <ul id="historyList"></ul>
  </details>

<script>
const VIDEO_EXT = ['.mp4','.webm','.ogg','.mov','.m3u8','.mkv','.avi','.flv'];
const IMAGE_EXT = ['.jpg','.jpeg','.png','.gif','.webp','.bmp','.svg','.ico','.avif'];
let history = JSON.parse(localStorage.getItem('mp_history') || '[]');
renderHistory();

document.getElementById('url').addEventListener('keydown', e => {
  if (e.key === 'Enter') preview();
});

function guessType(url) {
  const path = url.split('?')[0].toLowerCase();
  if (VIDEO_EXT.some(e => path.endsWith(e))) return 'video';
  if (IMAGE_EXT.some(e => path.endsWith(e))) return 'image';
  // 无法判断时尝试视频（video 标签失败时回退为图片）
  return 'auto';
}

function preview(urlOverride) {
  const input = document.getElementById('url');
  const url = (urlOverride || input.value).trim();
  if (!url) return;
  input.value = url;

  const area = document.getElementById('preview');
  const type = guessType(url);

  if (type === 'image') {
    showImage(area, url);
  } else if (type === 'video') {
    showVideo(area, url);
  } else {
    // auto: 尝试 video, 如果出错回退 image
    showVideo(area, url, () => showImage(area, url));
  }
  addHistory(url);
}

function showImage(area, url) {
  area.innerHTML = '';
  const img = document.createElement('img');
  img.src = url;
  img.onerror = () => { area.innerHTML = '<span class="placeholder">无法加载图片</span>'; };
  area.appendChild(img);
}

function showVideo(area, url, fallback) {
  area.innerHTML = '';
  const video = document.createElement('video');
  video.src = url;
  video.controls = true;
  video.autoplay = true;
  video.style.maxWidth = '100%';
  video.style.maxHeight = '80vh';
  video.onerror = () => {
    if (fallback) fallback();
    else area.innerHTML = '<span class="placeholder">无法加载视频</span>';
  };
  area.appendChild(video);
}

function clearAll() {
  document.getElementById('url').value = '';
  document.getElementById('preview').innerHTML = '<span class="placeholder">粘贴链接后点击「预览」</span>';
}

function addHistory(url) {
  history = history.filter(u => u !== url);
  history.unshift(url);
  if (history.length > 50) history.pop();
  localStorage.setItem('mp_history', JSON.stringify(history));
  renderHistory();
}

function renderHistory() {
  const sec = document.getElementById('historySection');
  const ul = document.getElementById('historyList');
  if (!history.length) { sec.style.display = 'none'; return; }
  sec.style.display = '';
  ul.innerHTML = history.map(u =>
    `<li onclick="preview('${u.replace(/'/g,"\\'")}');" title="${u}">${u}</li>`
  ).join('');
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 本地 HTTP 服务
# ---------------------------------------------------------------------------

class _PreviewHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_HTML_TEMPLATE.encode("utf-8"))

    def log_message(self, *args):
        pass  # 静默


def _start_server(port: int) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", port), _PreviewHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class MediaPreviewApp:
    def __init__(self, master: tk.Tk | tk.Toplevel):
        self.master = master
        master.title("DailyPy - 在线媒体预览")
        master.geometry("520x200")
        master.resizable(False, False)

        self._port = _find_free_port()
        self._server = _start_server(self._port)

        frame = ttk.Frame(master, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="媒体链接：").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.url_var, width=50)
        entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        entry.bind("<Return>", lambda _: self._open_with_url())

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=16)
        ttk.Button(btn_frame, text="在浏览器中预览", command=self._open_with_url).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="打开预览页面", command=self._open_blank).pack(side="left", padx=4)

        self.status_var = tk.StringVar(value=f"预览服务已启动  http://127.0.0.1:{self._port}")
        ttk.Label(frame, textvariable=self.status_var, foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky="w",
        )

        frame.columnconfigure(1, weight=1)
        master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _open_blank(self):
        webbrowser.open(f"http://127.0.0.1:{self._port}")

    def _open_with_url(self):
        url = self.url_var.get().strip()
        if url:
            encoded = json.dumps(url)  # JS-safe encoding
            # 通过 fragment 传递 URL，页面 JS 自动预览
            webbrowser.open(f"http://127.0.0.1:{self._port}#url={url}")
            self.status_var.set(f"已在浏览器中打开预览")
        else:
            self._open_blank()

    def _on_close(self):
        self._server.shutdown()
        self.master.destroy()


# ---------------------------------------------------------------------------
# 让 HTML 支持从 fragment 自动预览
# ---------------------------------------------------------------------------

# 在 HTML 的 script 尾部添加自动读取 hash 的逻辑
_AUTOPLAY_SCRIPT = """
;(function(){
  const hash = location.hash;
  if (hash && hash.startsWith('#url=')) {
    const u = decodeURIComponent(hash.substring(5));
    document.getElementById('url').value = u;
    setTimeout(() => preview(), 100);
  }
})();
"""

_HTML_TEMPLATE = _HTML_TEMPLATE.replace("</script>", _AUTOPLAY_SCRIPT + "</script>")


def main():
    root = tk.Tk()
    MediaPreviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

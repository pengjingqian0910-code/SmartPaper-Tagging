"""
SmartPaper 本地 HTTP API（供 Bookmarklet 呼叫）
預設監聽 http://localhost:7878

端點：
  GET /status          → {"status": "running"}
  GET /import?doi=...  → 匯入 DOI
  GET /import?arxiv=.. → 匯入 arXiv ID
"""

import http.server
import json
import threading
import urllib.parse

PORT = 7878


class _Handler(http.server.BaseHTTPRequestHandler):
    _importer = None   # 懶載入，共用一個實例

    # ── CORS preflight ──────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── 主要端點 ────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        if parsed.path == "/status":
            self._write({"status": "running", "port": PORT})
        else:
            self._write({"error": "use POST /import"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()

        if parsed.path != "/import":
            self._write({"error": "not found"})
            return

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            self._write({"success": False, "error": "JSON 解析失敗"})
            return

        self._do_import(data)

    # ── 匯入邏輯 ────────────────────────────────────────────────────
    def _do_import(self, data: dict):
        try:
            if _Handler._importer is None:
                from .quick_import import QuickImportService
                _Handler._importer = QuickImportService()

            # 有完整 meta（來自 bookmarklet）→ 用 import_with_meta
            if data.get("title"):
                paper, err = _Handler._importer.import_with_meta(data)
            else:
                # 只有 DOI 或 arXiv（舊路徑 fallback）
                text = data.get("doi") or data.get("arxiv") or ""
                if not text:
                    self._write({"success": False, "error": "缺少 doi、arxiv 或 title"})
                    return
                paper, err = _Handler._importer.import_from_text(text)

            if err:
                self._write({"success": False, "error": err})
            else:
                self._write({
                    "success": True,
                    "id": paper.id,
                    "title": paper.title,
                    "year": paper.year,
                    "tags": paper.tags[:5],
                })
        except Exception as exc:
            self._write({"success": False, "error": str(exc)})

    # ── 工具 ────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _write(self, obj: dict):
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass   # 靜音 server log


# ── 公開介面 ────────────────────────────────────────────────────────

def start(port: int = PORT):
    """在 daemon 執行緒中啟動 API server，不阻塞主執行緒。"""
    def _run():
        try:
            server = http.server.HTTPServer(("localhost", port), _Handler)
            server.serve_forever()
        except OSError:
            pass   # port 已被佔用（重複啟動）

    t = threading.Thread(target=_run, daemon=True, name="smartpaper-api")
    t.start()

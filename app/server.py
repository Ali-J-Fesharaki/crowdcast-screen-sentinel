"""HTTP Server and REST API for CrowdCast Screen Sentinel."""

import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.config import SCRATCH_DIR, SERVER_HOST, SERVER_PORT, WEB_DIR
from app.incus_bridge import IncusBridge
from app.sentinel_core import SentinelManager

logger = logging.getLogger(__name__)


class SentinelRequestHandler(BaseHTTPRequestHandler):
    bridge = IncusBridge()
    sentinel = SentinelManager(bridge)

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: Optional[str] = None):
        if not file_path.exists() or not file_path.is_file():
            self._send_json(404, {"error": "File not found"})
            return

        resolved_type = content_type
        if not resolved_type:
            guessed_type, _ = mimetypes.guess_type(str(file_path))
            resolved_type = guessed_type or "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", resolved_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _read_json_body(self) -> Dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Static assets
        if path in ["/", "/index.html"]:
            self._send_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        elif path == "/style.css":
            self._send_file(WEB_DIR / "style.css", "text/css; charset=utf-8")
            return
        elif path == "/app.js":
            self._send_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        elif path == "/api/preview.png":
            frame_path = SCRATCH_DIR / "latest_preview.png"
            self._send_file(frame_path, "image/png")
            return

        # REST Endpoints
        elif path == "/api/status":
            try:
                state = self.sentinel.get_full_state()
                self._send_json(200, state)
            except Exception as e:
                logger.exception("Error in /api/status")
                self._send_json(500, {"error": str(e)})
            return

        elif path == "/api/luma":
            try:
                luma = self.sentinel.luma_sampler.sample_latest_frame(force=True)
                self._send_json(200, luma)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        elif path == "/api/instances":
            try:
                instances = self.bridge.get_instances()
                self._send_json(200, {"instances": instances})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        if path == "/api/windows/add":
            wm_class = body.get("wm_class", "").strip()
            if not wm_class:
                self._send_json(400, {"error": "Missing wm_class parameter"})
                return
            res = self.sentinel.add_to_monitoring(wm_class)
            self._send_json(200 if res.get("success") else 500, res)
            return

        elif path == "/api/windows/remove":
            wm_class = body.get("wm_class", "").strip()
            if not wm_class:
                self._send_json(400, {"error": "Missing wm_class parameter"})
                return
            res = self.sentinel.remove_from_monitoring(wm_class)
            self._send_json(200 if res.get("success") else 500, res)
            return

        elif path == "/api/windows/fix":
            wm_class = body.get("wm_class", "").strip()
            if not wm_class:
                self._send_json(400, {"error": "Missing wm_class parameter"})
                return
            res = self.sentinel.fix_blackout(wm_class)
            self._send_json(200 if res.get("success") else 500, res)
            return

        elif path == "/api/windows/focus":
            wm_class = body.get("wm_class", "").strip()
            if not wm_class:
                self._send_json(400, {"error": "Missing wm_class parameter"})
                return
            ok = self.bridge.focus_window(wm_class)
            self._send_json(200, {"success": ok, "focused": wm_class})
            return

        elif path == "/api/windows/whitelist-all":
            res = self.sentinel.whitelist_all_open()
            self._send_json(200 if res.get("success") else 500, res)
            return

        elif path == "/api/agent/restart":
            ok, msg = self.bridge.restart_agent()
            self._send_json(200 if ok else 500, {"success": ok, "output": msg})
            return

        elif path == "/api/upload/start":
            ok, msg = self.bridge.start_manual_upload()
            self._send_json(200 if ok else 500, {
                "success": ok,
                "message_fa": "فرایند آپلود دستی با موفقیت آغاز شد.",
                "message_en": "Manual upload override started successfully.",
                "output": msg
            })
            return

        elif path == "/api/upload/pause":
            ok, msg = self.bridge.pause_manual_upload()
            self._send_json(200 if ok else 500, {
                "success": ok,
                "message_fa": "آپلود متوقف شد و به زمان‌بندی تهران بازگشت.",
                "message_en": "Upload paused and returned to Tehran schedule.",
                "output": msg
            })
            return

        elif path == "/api/settings/update":
            res = self.sentinel.update_settings(body)
            self._send_json(200 if res.get("success") else 500, res)
            return

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def log_message(self, format, *args):
        # Concise logging
        logger.info(f"{self.address_string()} - {format % args}")


def run_server(host: str = SERVER_HOST, port: int = SERVER_PORT):
    server = ThreadingHTTPServer((host, port), SentinelRequestHandler)
    print(f"============================================================")
    print(f"🛡️  CrowdCast Screen Sentinel Dashboard Running!")
    print(f"👉 Local Access:   http://localhost:{port}")
    print(f"👉 Network/VM URL: http://10.5.48.1:{port}")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()

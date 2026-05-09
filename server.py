import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
LIST_FILE = ROOT / "stl_files.txt"
INDEX_FILE = ROOT / "index.html"
PORT = 8765


def load_files():
    if not LIST_FILE.exists():
        return []
    raw = LIST_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = []
    for line in raw:
        p = line.strip().lstrip("﻿")
        if not p:
            continue
        if Path(p).is_file():
            out.append(p)
    return out


FILES = load_files()
FILES_LOCK = threading.Lock()
SCAN_STATE = {"running": False, "started": 0.0, "finished": 0.0, "error": None}
SCAN_LOCK = threading.Lock()


def run_scan():
    global FILES
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "Get-ChildItem -Path C:\\ -Filter *.stl -Recurse -File -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty FullName "
        "| Out-File -FilePath '" + str(LIST_FILE) + "' -Encoding utf8"
    ]
    try:
        subprocess.run(cmd, check=False, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        new_files = load_files()
        with FILES_LOCK:
            FILES = new_files
        with SCAN_LOCK:
            SCAN_STATE["finished"] = time.time()
            SCAN_STATE["error"] = None
    except Exception as e:
        with SCAN_LOCK:
            SCAN_STATE["error"] = str(e)
            SCAN_STATE["finished"] = time.time()
    finally:
        with SCAN_LOCK:
            SCAN_STATE["running"] = False


def start_scan():
    with SCAN_LOCK:
        if SCAN_STATE["running"]:
            return False
        SCAN_STATE["running"] = True
        SCAN_STATE["started"] = time.time()
        SCAN_STATE["error"] = None
    threading.Thread(target=run_scan, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send_bytes(INDEX_FILE.read_bytes(), "text/html; charset=utf-8")
            return

        if path == "/api/list":
            with FILES_LOCK:
                snapshot = list(FILES)
            entries = [
                {"id": i, "path": p, "name": os.path.basename(p),
                 "dir": os.path.dirname(p), "size": os.path.getsize(p) if os.path.exists(p) else 0}
                for i, p in enumerate(snapshot)
            ]
            self._json(200, {"files": entries})
            return

        if path == "/api/scan-status":
            with SCAN_LOCK:
                state = dict(SCAN_STATE)
            with FILES_LOCK:
                state["count"] = len(FILES)
            self._json(200, state)
            return

        if path.startswith("/api/file/"):
            try:
                idx = int(path.rsplit("/", 1)[1])
                with FILES_LOCK:
                    fp = FILES[idx]
            except (ValueError, IndexError):
                self._json(404, {"error": "not found"})
                return
            if not os.path.exists(fp):
                self._json(410, {"error": "file gone"})
                return
            with open(fp, "rb") as f:
                self._send_bytes(f.read(), "application/octet-stream")
            return

        self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/rescan":
            started = start_scan()
            self._json(200, {"started": started})
            return

        if parsed.path == "/api/delete":
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                idx = int(body["id"])
            except Exception as e:
                self._json(400, {"error": f"bad request: {e}"})
                return

            with FILES_LOCK:
                try:
                    target_path = FILES[idx]
                except IndexError:
                    self._json(404, {"error": "id out of range"})
                    return

            if not os.path.exists(target_path):
                with FILES_LOCK:
                    if idx < len(FILES) and FILES[idx] == target_path:
                        del FILES[idx]
                self._json(410, {"error": "file already gone", "removed": True})
                return

            ps_script = (
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                "'" + target_path.replace("'", "''") + "',"
                "'OnlyErrorDialogs','SendToRecycleBin')"
            )
            try:
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True, text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                if proc.returncode != 0 or os.path.exists(target_path):
                    err = (proc.stderr or proc.stdout or "unknown error").strip().splitlines()
                    self._json(500, {"error": f"delete failed: {err[0] if err else 'unknown'}"})
                    return
            except Exception as e:
                self._json(500, {"error": f"delete failed: {e}"})
                return

            with FILES_LOCK:
                if idx < len(FILES) and FILES[idx] == target_path:
                    del FILES[idx]
                count = len(FILES)
            self._json(200, {"ok": True, "remaining": count})
            return

        if parsed.path != "/api/rename":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            idx = int(body["id"])
            new_name = str(body["name"]).strip()
        except Exception as e:
            self._json(400, {"error": f"bad request: {e}"})
            return

        if not new_name or "\\" in new_name or "/" in new_name:
            self._json(400, {"error": "invalid filename"})
            return
        if not new_name.lower().endswith(".stl"):
            new_name += ".stl"

        with FILES_LOCK:
            try:
                old_path = FILES[idx]
            except IndexError:
                self._json(404, {"error": "id out of range"})
                return

        directory = os.path.dirname(old_path)
        new_path = os.path.join(directory, new_name)

        if os.path.abspath(new_path) == os.path.abspath(old_path):
            self._json(200, {"ok": True, "path": old_path, "name": os.path.basename(old_path)})
            return

        if os.path.exists(new_path):
            self._json(409, {"error": "a file with that name already exists"})
            return

        try:
            os.rename(old_path, new_path)
        except OSError as e:
            self._json(500, {"error": f"rename failed: {e}"})
            return

        with FILES_LOCK:
            if idx < len(FILES) and FILES[idx] == old_path:
                FILES[idx] = new_path
        self._json(200, {"ok": True, "path": new_path, "name": os.path.basename(new_path)})


def main():
    print(f"Loaded {len(FILES)} STL files")
    if not FILES:
        print("No STL files found in stl_files.txt — scan may not have completed.")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Serving at {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()

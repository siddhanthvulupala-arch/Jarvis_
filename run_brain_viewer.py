"""Runner and HTTP server for the JARVIS 3D Brain Viewer."""
import argparse
import http.server
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 8766
UI_DIR = Path(__file__).resolve().parent / "UI"


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def find_free_port(start_port: int = DEFAULT_PORT) -> int:
    port = start_port
    while port < start_port + 50:
        if is_port_free(port):
            return port
        port += 1
    return start_port


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        if parsed.path == "/api/log":
            params = parse_qs(parsed.query)
            msg = params.get("msg", [None])[0]
            err = params.get("error", [None])[0]
            if err:
                print(f"\n[BROWSER ERROR] {err}", flush=True)
            elif msg:
                print(f"\n[BROWSER LOG] {msg}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        super().do_GET()

    def do_POST(self):
        from urllib.parse import urlparse
        import base64
        parsed = urlparse(self.path)
        if parsed.path == "/api/screenshot":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            if body.startswith("data:image/png;base64,"):
                body = body.split(",", 1)[1]
            data = base64.b64decode(body)
            out_file = Path("brain_verified_render.png").resolve()
            out_file.write_bytes(data)
            print(f"\n[SERVER] Received WebGL screenshot ({len(data)} bytes) saved to {out_file}!", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        self.send_error(404)

    def log_message(self, format, *args):
        # Keep terminal output clean
        pass

    def end_headers(self):
        # Enable CORS and caching headers for 3D assets
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def start_server(port: int):
    server = socketserver.TCPServer(("127.0.0.1", port), QuietHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server, server_thread


def verify_in_headless_browser(url: str, output_image: str = "brain_verification.png"):
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_bin = next((p for p in edge_paths if os.path.exists(p)), None)
    if not edge_bin:
        print("[VERIFY] Edge executable not found, skipping headless screenshot.")
        return False

    out_path = Path(output_image).resolve()
    print(f"[VERIFY] Capturing headless screenshot with Edge to {out_path}...")

    cmd = [
        edge_bin,
        "--headless",
        "--hide-scrollbars",
        "--window-size=1280,720",
        f"--screenshot={out_path}",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        url,
    ]

    try:
        # Give WebGL 3-4 seconds to load and render
        time.sleep(1.0)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"[VERIFY] SUCCESS: Screenshot captured ({out_path.stat().st_size} bytes).")
            return True
        else:
            print(f"[VERIFY] Failed to capture screenshot. Return code: {res.returncode}")
            return False
    except Exception as err:
        print(f"[VERIFY] Headless verification error: {err}")
        return False


def main():
    parser = argparse.ArgumentParser(description="JARVIS 3D Brain Viewer Runner")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to serve the viewer on")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open default browser")
    parser.add_argument("--verify", action="store_true", help="Run headless verification screenshot")
    args = parser.parse_args()

    port = find_free_port(args.port)
    server, thread = start_server(port)

    url = f"http://127.0.0.1:{port}/brain.html"
    print("=" * 60)
    print("  JARVIS // 3D HUMAN BRAIN MODEL (STEP 1)")
    print(f"  Live Server URL: {url}")
    print(f"  Serving Directory: {UI_DIR}")
    print("=" * 60)

    if args.verify:
        success = verify_in_headless_browser(url)
        if not success:
            print("[WARN] Headless verification could not complete screenshot.")

    if not args.no_browser:
        print("[LAUNCH] Opening browser preview...")
        webbrowser.open(url)

    print("[RUNNING] 3D Brain Model server is active. Press Ctrl+C to terminate.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOPPING] Shutting down server...")
        server.shutdown()


if __name__ == "__main__":
    main()

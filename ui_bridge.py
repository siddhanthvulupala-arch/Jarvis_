"""Optional loopback HTTP bridge between the JARVIS core and its UI."""
from __future__ import annotations

import atexit
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse
import urllib.request

# Location of the PID file used to detect stale JARVIS instances.
_PID_DIR = Path(__file__).resolve().parent
_PID_FILE = _PID_DIR / ".jarvis.pid"


class UIBridgeError(Exception):
    """Base exception for UIBridge errors."""
    pass


class UnrelatedPortOccupiedError(UIBridgeError):
    """Raised when the UI port is occupied by an unrelated process."""
    pass


class StaleProcessCleanupError(UIBridgeError):
    """Raised when a stale process could not be cleaned up or port not freed."""
    pass


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID exists (Windows-safe)."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_pid_for_port(port: int) -> int | None:
    """Find the process ID currently listening on *port*."""
    if os.name == "nt":
        try:
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in output.splitlines():
                parts = line.strip().split()
                # Netstat format: TCP  127.0.0.1:8765  0.0.0.0:0  LISTENING  <PID>
                if len(parts) >= 5 and parts[-2] == "LISTENING" and parts[1].endswith(f":{port}"):
                    return int(parts[-1])
        except Exception:
            pass
        return None

    # macOS / Linux: Try psutil first, then lsof
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                return conn.pid
    except Exception:
        pass
    try:
        output = subprocess.check_output(
            ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        pids = [int(p) for p in output.strip().splitlines() if p.isdigit()]
        if pids:
            return pids[0]
    except Exception:
        pass
    return None


def _probe_health(port: int, timeout: float = 2.0) -> bool:
    """Return True if a JARVIS health endpoint is responding on *port*."""
    try:
        url = f"http://127.0.0.1:{port}/api/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("service") == "jarvis"
    except Exception:
        return False


def _get_process_cmdline(pid: int) -> str:
    """Retrieve process command line for identification."""
    try:
        import psutil
        p = psutil.Process(pid)
        return " ".join(p.cmdline())
    except Exception:
        pass
    if os.name == "nt":
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            return res.stdout.strip()
        except Exception:
            return ""
    else:
        try:
            res = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3)
            return res.stdout.strip()
        except Exception:
            return ""


def _is_jarvis_process(pid: int) -> bool:
    """Check if the PID belongs to a JARVIS process."""
    cmdline = _get_process_cmdline(pid).lower()
    return "jarvis" in cmdline


def _port_in_use(port: int) -> bool:
    """Return True if *port* is currently bound on loopback."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        return result == 0
    except OSError:
        return False
    finally:
        sock.close()


def _write_pid(pid: int | None = None) -> None:
    """Write the current process PID to the PID file."""
    pid = pid if pid is not None else os.getpid()
    try:
        _PID_FILE.write_text(str(pid), encoding="utf-8")
    except OSError as error:
        print(f"Could not write PID file: {error}")


def _read_pid() -> int | None:
    """Read the PID from the PID file, or None if missing/invalid."""
    try:
        return int(_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _remove_pid() -> None:
    """Remove the PID file if it points to this process or a dead process."""
    try:
        stored = _read_pid()
        if stored is None or stored == os.getpid() or not _is_pid_alive(stored):
            _PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _terminate_pid(pid: int) -> bool:
    """Ask a process to terminate gracefully, then forcibly if needed."""
    if not _is_pid_alive(pid):
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return True  # already gone

    # Wait up to 3 seconds for graceful exit
    for _ in range(30):
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.1)

    # Force kill if still alive
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    for _ in range(10):
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.1)

    return not _is_pid_alive(pid)


def retire_stale_bridge(port: int) -> None:
    """Detect and clean up a stale JARVIS instance holding *port*.

    Safety rules:
    - If the port is free, do nothing.
    - If the port is occupied:
      1. Check whether occupant is a JARVIS instance (via /api/health probe,
         matching PID file, or process command line).
      2. If NOT a JARVIS process, ABORT by raising UnrelatedPortOccupiedError.
      3. If it IS a stale JARVIS instance, terminate it (SIGTERM then taskkill)
         and wait for the port to be released.
      4. If port cannot be freed after cleanup, ABORT by raising StaleProcessCleanupError.
    """
    if not _port_in_use(port):
        return

    listening_pid = _get_pid_for_port(port)
    stored_pid = _read_pid()
    is_health_jarvis = _probe_health(port)

    # Determine if the occupant belongs to JARVIS
    is_jarvis = is_health_jarvis
    if not is_jarvis and stored_pid is not None and listening_pid == stored_pid:
        is_jarvis = True
    if not is_jarvis and listening_pid is not None and _is_jarvis_process(listening_pid):
        is_jarvis = True

    if not is_jarvis:
        pid_info = f" (PID {listening_pid})" if listening_pid else ""
        msg = (
            f"Port {port} is occupied by an unrelated process{pid_info}. "
            f"Please terminate that application or configure JARVIS_UI_PORT before starting JARVIS."
        )
        print(f"\n[FATAL] {msg}")
        raise UnrelatedPortOccupiedError(msg)

    # Determine which PID to terminate
    target_pid = None
    if stored_pid is not None and _is_pid_alive(stored_pid):
        target_pid = stored_pid
    elif listening_pid is not None and _is_pid_alive(listening_pid):
        target_pid = listening_pid

    if target_pid is not None:
        if target_pid == os.getpid():
            return
        print(f"Detected stale JARVIS instance (PID {target_pid}) holding port {port}. Retiring...")
        if _terminate_pid(target_pid):
            print(f"Stale JARVIS instance (PID {target_pid}) terminated.")
        else:
            print(f"Warning: Could not terminate stale JARVIS (PID {target_pid}).")
    elif stored_pid is not None:
        print(f"PID file pointed to {stored_pid} which is already gone.")

    # Wait up to 5 seconds for the port to become free
    deadline = time.monotonic() + 5.0
    while _port_in_use(port):
        if time.monotonic() > deadline:
            msg = (
                f"Port {port} is still occupied after attempting to retire stale JARVIS instance. "
                f"Startup aborted."
            )
            print(f"\n[FATAL] {msg}")
            raise StaleProcessCleanupError(msg)
        time.sleep(0.2)

    print(f"Port {port} is now free.")


class UIBridge:
    """Serve the local UI and forward its text requests into JARVIS handlers."""

    CLIENT_TIMEOUT_SECONDS = 12
    MAX_MESSAGE_BYTES = 16_384

    def __init__(self, ui_path: Path, handle_text: Callable[[str], None], port: int = 8765):
        self.ui_path = Path(ui_path)
        self.handle_text = handle_text
        self.port = port
        self._lock = threading.RLock()
        self._hand_state_changed = threading.Condition(self._lock)
        self._latest_hand_state = {
            "tracking": False,
            "hand": None,
            "x": 0.5,
            "y": 0.5,
            "timestamp": time.time(),
            "hands": [],
            "fps": 0.0,
        }
        self._hand_state_revision = 0
        self._request_lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=256)
        self._event_id = 0
        self._state = "idle"
        self._mode: str | None = None
        self._last_client_seen = 0.0
        self._telemetry_provider: Callable[[], dict] | None = None
        self._speech_envelope: list[float] = []
        self._speech_start_time = 0.0
        self._speech_duration = 0.0
        self._speech_fps = 30
        self._speech_text = ""
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stopped = False

    def start(self) -> str:
        # --- Stale-instance cleanup ---
        retire_stale_bridge(self.port)

        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:
                return

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/UI.html"):
                    try:
                        body = bridge.ui_path.read_bytes()
                    except OSError:
                        self.send_error(404, "JARVIS UI file not found")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parsed.path == "/api/events":
                    try:
                        since = max(0, int(parse_qs(parsed.query).get("since", ["0"])[0]))
                    except ValueError:
                        since = 0
                    self._send_json(200, bridge.poll(since))
                    return
                if parsed.path == "/api/hand-state/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    revision = -1
                    try:
                        while True:
                            with bridge._hand_state_changed:
                                bridge._hand_state_changed.wait_for(
                                    lambda: bridge._hand_state_revision != revision or bridge._stopped,
                                    timeout=15.0,
                                )
                                if bridge._stopped:
                                    break
                                revision = bridge._hand_state_revision
                                payload = {"revision": revision, "state": dict(bridge._latest_hand_state)}
                            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                if parsed.path == "/api/health":
                    self._send_json(200, {"ok": True, "service": "jarvis"})
                    return
                if parsed.path == "/api/status":
                    self._send_json(200, bridge.get_status())
                    return
                self.send_error(404)

            def do_POST(self) -> None:
                if self.path not in ("/api/message", "/api/mode"):
                    self.send_error(404)
                    return
                origin = self.headers.get("Origin")
                allowed_origins = {
                    f"http://127.0.0.1:{bridge.port}",
                    f"http://localhost:{bridge.port}",
                }
                if origin and origin not in allowed_origins:
                    self._send_json(403, {"ok": False, "error": "Unexpected request origin"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"ok": False, "error": "Invalid content length"})
                    return
                if length <= 0 or length > bridge.MAX_MESSAGE_BYTES:
                    self._send_json(413, {"ok": False, "error": "Request is empty or too large"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(400, {"ok": False, "error": "Expected a JSON request"})
                    return
                if not isinstance(payload, dict):
                    self._send_json(400, {"ok": False, "error": "Expected a JSON object"})
                    return

                if self.path == "/api/mode":
                    if payload.get("type") != "MODE_CHANGED" or payload.get("mode") not in ("text", "voice"):
                        self._send_json(400, {"ok": False, "error": "Expected MODE_CHANGED with text or voice mode"})
                        return
                    bridge.set_mode(payload["mode"])
                    self._send_json(200, {"ok": True, "mode": payload["mode"]})
                    return

                if payload.get("type") not in ("USER_TEXT", "VOICE_INPUT"):
                    self._send_json(400, {"ok": False, "error": "Expected USER_TEXT or VOICE_INPUT"})
                    return
                text = payload.get("text")
                if not isinstance(text, str) or not text.strip():
                    self._send_json(400, {"ok": False, "error": "Message text is required"})
                    return
                bridge.touch_client()
                try:
                    with bridge._request_lock:
                        bridge.set_state("thinking")
                        bridge.handle_text(text.strip())
                    self._send_json(200, {"ok": True})
                except Exception as error:
                    bridge.publish_error(str(error))
                    self._send_json(500, {"ok": False, "error": "JARVIS could not process that request"})

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="jarvis-ui-bridge", daemon=True)
        self._thread.start()

        # Record our PID so future instances can find and retire us.
        _write_pid()
        atexit.register(self.stop)

        return f"http://127.0.0.1:{self.port}/"

    def stop(self) -> None:
        """Shut down the HTTP server and clean up the PID file."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._hand_state_changed.notify_all()
            server = self._server
            self._server = None

        if server is not None:
            try:
                shut_thread = threading.Thread(target=server.shutdown, daemon=True)
                shut_thread.start()
                shut_thread.join(timeout=1.5)
                server.server_close()
            except Exception:
                pass
        self._cleanup()

    def _cleanup(self) -> None:
        """Remove the PID file if it still belongs to this process."""
        _remove_pid()

    def set_telemetry_provider(self, provider: Callable[[], dict]) -> None:
        with self._lock:
            self._telemetry_provider = provider

    def get_telemetry(self) -> dict:
        with self._lock:
            provider = self._telemetry_provider
        if provider is not None:
            try:
                result = provider()
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
        return {}

    def get_status(self) -> dict:
        with self._lock:
            return {
                "connected": True,
                "state": self._state,
                "mode": self._mode,
                "amplitude": self.get_current_amplitude(),
                "telemetry": self.get_telemetry(),
            }

    def start_speech(self, text: str, duration: float, envelope: list[float], fps: int = 30) -> None:
        with self._lock:
            self._state = "speaking"
            self._speech_text = str(text)
            self._speech_duration = float(max(0.0, duration))
            self._speech_envelope = [float(v) for v in envelope]
            self._speech_fps = int(max(1, fps))
            self._speech_start_time = time.monotonic()
            self._append_event({
                "type": "speech_start",
                "text": str(text),
                "duration": round(self._speech_duration, 3),
                "envelope": self._speech_envelope,
                "fps": self._speech_fps,
            })
            self._append_event({"type": "state", "state": "speaking"})

    def stop_speech(self) -> None:
        with self._lock:
            self._speech_envelope = []
            self._speech_start_time = 0.0
            self._speech_duration = 0.0
            self._append_event({"type": "speech_end"})
            target_state = "listening" if self._mode == "voice" else "idle"
            self._state = target_state
            self._append_event({"type": "state", "state": target_state})

    def get_current_amplitude(self) -> float:
        with self._lock:
            if not self._speech_envelope or self._speech_start_time <= 0.0:
                return 0.0
            elapsed = time.monotonic() - self._speech_start_time
            if elapsed < 0.0 or elapsed > self._speech_duration + 0.1:
                return 0.0
            frame_idx = int(elapsed * self._speech_fps)
            if 0 <= frame_idx < len(self._speech_envelope):
                return float(self._speech_envelope[frame_idx])
            return 0.0

    def publish_user_speech(self, text: str) -> None:
        with self._lock:
            self._append_event({"type": "user_speech", "text": str(text)})

    def poll(self, since: int = 0) -> dict:
        self.touch_client()
        with self._lock:
            events = [event for event in self._events if event["id"] > since]
            amplitude = self.get_current_amplitude()
            telemetry = self.get_telemetry()
            return {
                "connected": True,
                "state": self._state,
                "mode": self._mode,
                "amplitude": amplitude,
                "telemetry": telemetry,
                "events": events,
            }

    def touch_client(self) -> None:
        with self._lock:
            self._last_client_seen = time.monotonic()

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode
            self._last_client_seen = time.monotonic()
        self.set_state("listening" if mode == "voice" else "idle")

    def should_listen(self) -> bool:
        with self._lock:
            ui_is_connected = time.monotonic() - self._last_client_seen < self.CLIENT_TIMEOUT_SECONDS
            return not ui_is_connected or self._mode != "text"

    @property
    def mode(self) -> str | None:
        with self._lock:
            return self._mode

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
            self._append_event({"type": "state", "state": state})

    def publish_response(self, text: str) -> None:
        with self._lock:
            self._append_event({"type": "response", "text": str(text)})

    def publish_error(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._append_event({"type": "error", "text": message[:500]})
            self._append_event({"type": "state", "state": "error"})

    def _append_event(self, event: dict) -> None:
        self._event_id += 1
        self._events.append({"id": self._event_id, **event})

    def set_hand_state(self, state: dict) -> None:
        """Replace the current sensor snapshot and notify stream clients."""
        with self._hand_state_changed:
            self._latest_hand_state = dict(state)
            self._hand_state_revision += 1
            self._hand_state_changed.notify_all()

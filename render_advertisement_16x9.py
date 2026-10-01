#!/usr/bin/env python3
"""
JARVIS 16:9 Landscape Cinematic Advertisement Video Generator
Renders 1020 frames (34.0s @ 30 FPS) at 1920x1080, and muxes with the
master electronic score, sound design, and JARVIS voice lines.
"""

import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

PORT = 8992
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(WORKSPACE_DIR, "UI")
FRAMES_DIR = os.path.join(WORKSPACE_DIR, "temp_ad_frames")
SOUNDTRACK = os.path.join(WORKSPACE_DIR, "cinematic_soundtrack.wav")
OUTPUT_VIDEO = os.path.join(WORKSPACE_DIR, "jarvis_advertisement_16x9.mp4")

done_event = threading.Event()
frames_received = 0
total_bytes = 0

class AdHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def do_POST(self):
        global frames_received, total_bytes
        parsed = urlparse(self.path)
        
        if parsed.path == '/frame':
            query = parse_qs(parsed.query)
            frame_idx = int(query.get('index', [frames_received])[0])
            content_length = int(self.headers['Content-Length'])
            data = self.rfile.read(content_length)
            
            frame_path = os.path.join(FRAMES_DIR, f"frame_{frame_idx:05d}.jpg")
            with open(frame_path, "wb") as f:
                f.write(data)
                
            frames_received += 1
            total_bytes += len(data)
            
            if frames_received % 60 == 0:
                print(f"[RENDER] Captured frame {frames_received}/1020 ({(frames_received/30):.1f}s) - {len(data)//1024} KB")

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
            
        elif parsed.path == '/done':
            print(f"\n[RENDER] All frames received: {frames_received} frames ({total_bytes / (1024*1024):.1f} MB)")
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
            done_event.set()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def main():
    print("=" * 65)
    print("  JARVIS 16:9 CINEMATIC ADVERTISEMENT GENERATOR (1920x1080)")
    print("=" * 65)

    if not os.path.exists(SOUNDTRACK):
        print(f"[ERROR] Soundtrack not found: {SOUNDTRACK}")
        print("Please run generate_cinematic_audio.py first.")
        sys.exit(1)

    if os.path.exists(FRAMES_DIR):
        shutil.rmtree(FRAMES_DIR, ignore_errors=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)

    # 1. Start Local Asset & Frame Server
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), AdHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"[SERVER] Asset server running on http://127.0.0.1:{PORT}/")

    # 2. Locate Chrome Executable
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    chrome_path = None
    for p in chrome_candidates:
        if os.path.exists(p):
            chrome_path = p
            break

    if not chrome_path:
        print("[ERROR] Chrome or Edge executable not found!")
        sys.exit(1)

    print(f"[BROWSER] Using browser engine: {chrome_path}")

    # 3. Launch Headless Browser to execute WebGL Scene & Frame Capture
    target_url = f"http://127.0.0.1:{PORT}/advertisement_16x9.html?record=1"
    chrome_args = [
        chrome_path,
        "--headless=new",
        "--use-gl=angle",
        "--use-angle=d3d11",
        "--disable-gpu-vsync",
        "--window-size=1920,1080",
        "--no-first-run",
        "--no-default-browser-check",
        target_url
    ]

    print(f"[BROWSER] Launching headless 1920x1080 renderer...")
    proc = subprocess.Popen(chrome_args)

    start_time = time.time()
    print("[RENDER] Rendering 34.0s cinematic sequence at 30 FPS (1020 frames)...")
    success = done_event.wait(timeout=360)

    try:
        proc.kill()
        proc.wait(timeout=3)
    except Exception:
        pass
    server.shutdown()

    if not success or frames_received == 0:
        print(f"[ERROR] Frame capture timed out or failed! Frames received: {frames_received}")
        sys.exit(1)

    render_duration = time.time() - start_time
    print(f"[RENDER] Completed in {render_duration:.1f}s ({frames_received / render_duration:.1f} FPS render speed)")

    # 4. Encode Video & Mux with Soundtrack using FFmpeg
    print("\n[FFMPEG] Encoding H.264 video and muxing with cinematic soundtrack...")
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-framerate", "30",
        "-i", os.path.join(FRAMES_DIR, "frame_%05d.jpg"),
        "-i", SOUNDTRACK,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-crf", "18",
        "-preset", "slow",
        "-c:a", "aac",
        "-b:a", "256k",
        "-shortest",
        "-movflags", "+faststart",
        OUTPUT_VIDEO
    ]

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] FFmpeg encoding failed:\n{result.stderr}")
        sys.exit(1)

    # 5. Clean up temporary frames
    shutil.rmtree(FRAMES_DIR, ignore_errors=True)

    if os.path.exists(OUTPUT_VIDEO):
        file_size_mb = os.path.getsize(OUTPUT_VIDEO) / (1024 * 1024)
        print("=" * 65)
        print("  JARVIS 16:9 CINEMATIC ADVERTISEMENT COMPLETED!")
        print("=" * 65)
        print(f"  Output Path: {OUTPUT_VIDEO}")
        print(f"  File Size:   {file_size_mb:.2f} MB")
        print(f"  Resolution:  1920 x 1080 (16:9 Landscape Full HD)")
        print(f"  Duration:    34.0 seconds")
        print(f"  Frame Rate:  30.0 FPS (1,020 frames)")
        print(f"  Video Codec: H.264 High Profile (yuv420p)")
        print(f"  Audio Track: 44.1 kHz Stereo AAC (Score + Voice Lines + FX)")
        print("=" * 65)
    else:
        print("[ERROR] Output video file was not found!")
        sys.exit(1)

if __name__ == '__main__':
    main()

import os
import sys
import threading
from pathlib import Path

# Add the project root to sys.path so we can import from app/
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Set the flag to disable the browser popup
os.environ["JARVIS_NO_BROWSER"] = "1"

# Import JARVIS after setting the environment variable
import jarvis
from app.main import start_ui

import argparse

def run_jarvis_backend(text_mode=False):
    print(f"[DESKTOP APP] Starting Python backend (text_mode={text_mode})...")
    if text_mode:
        jarvis.debug_text_loop()
    else:
        jarvis.main()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JARVIS Desktop App")
    parser.add_argument("--text", action="store_true", help="Start JARVIS in text mode")
    args = parser.parse_args()

    # Start the backend in a daemon thread so it exits when the app exits
    backend_thread = threading.Thread(target=run_jarvis_backend, args=(args.text,), daemon=True)
    backend_thread.start()

    # Create and run the desktop app shell (this blocks until the window is closed)
    print("[DESKTOP APP] Launching UI Window...")
    start_ui()
    
    # Send a shutdown request to JARVIS to clean up gracefully
    print("[DESKTOP APP] Window closed. Requesting backend shutdown...")
    jarvis.request_shutdown("app_closed")
    
    # Allow some time for graceful shutdown
    backend_thread.join(timeout=3.0)
    
    sys.exit(0)

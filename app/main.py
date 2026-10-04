import os
import webview
import time
import threading

def start_ui():
    port = os.getenv("JARVIS_UI_PORT", "8765")
    url = f"http://127.0.0.1:{port}"
    
    # Wait slightly to ensure the backend HTTP server has bound to the port
    time.sleep(1.5)
    
    window = webview.create_window(
        title="JARVIS Core",
        url=url,
        width=1280,
        height=720,
        background_color="#020100",
        frameless=False,  # We can make it frameless later if desired
    )
    
    # Start the webview event loop on the main thread
    webview.start(debug=False)

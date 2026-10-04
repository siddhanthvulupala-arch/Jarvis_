import time
from hand_tracking_controller import start_hand_tracking, stop_hand_tracking

class MockUIBridge:
    def _append_event(self, event):
        pass

    def set_hand_state(self, state):
        pass

print("Starting hand tracking...")
bridge = MockUIBridge()
start_hand_tracking(ui_bridge=bridge)

try:
    print("Running for 15 seconds to gather metrics...")
    for i in range(15):
        time.sleep(1)
        print(f"Elapsed: {i+1}s")
except KeyboardInterrupt:
    pass
finally:
    stop_hand_tracking()
    print("Stopped.")

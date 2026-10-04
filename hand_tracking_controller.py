import cv2
import mediapipe as mp
import time
import threading
import logging
import psutil
from hand_gesture_engine import HandGestureEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HandTrackingController:
    def __init__(self, ui_bridge=None, event_callback=None):
        self.ui_bridge = ui_bridge
        self.event_callback = event_callback
        self.active = False
        self.thread = None
        self.cap = None

        # Presence and primary-hand tracking are separate from pose state.
        self.hand_present = False
        self.active_hand = None
        self.gesture_engine = HandGestureEngine()
        self.gesture_lock = threading.Lock()
        self._last_gesture_diagnostic = 0.0

        # Metrics
        self.fps = 0
        self.frame_count = 0
        self.start_time = 0

        # Static landmark connections to avoid drawing_utils dependencies
        self.HAND_CONNECTIONS = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (5, 9), (9, 10), (10, 11), (11, 12),
            (9, 13), (13, 14), (14, 15), (15, 16),
            (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)
        ]

    def start_hand_tracking(self, ui_bridge=None, event_callback=None):
        if self.active:
            logger.info("Hand tracking is already active.")
            return False

        logger.info("Starting hand tracking...")
        self.active = True
        with self.gesture_lock:
            self.gesture_engine.reset()
        if ui_bridge:
            self.ui_bridge = ui_bridge
        if event_callback:
            self.event_callback = event_callback
        if self.ui_bridge:
            self.ui_bridge.set_hand_state({
                "tracking": True, "hand": None, "x": 0.5, "y": 0.5,
                "timestamp": time.time(), "hands": [], "fps": 0.0,
            })
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()

        if self.ui_bridge:
            self.ui_bridge._append_event({"type": "hand_tracking_state", "state": "ON"})
        return True

    def stop_hand_tracking(self):
        if not self.active:
            logger.info("Hand tracking is already inactive.")
            return False

        logger.info("Stopping hand tracking...")
        self.active = False
        if self.ui_bridge:
            self.ui_bridge.set_hand_state({
                "tracking": False, "hand": None, "x": 0.5, "y": 0.5,
                "timestamp": time.time(), "hands": [], "fps": 0.0,
            })
        if self.thread:
            self.thread.join(timeout=2.0)
        with self.gesture_lock:
            self.gesture_engine.reset()

        if self.ui_bridge:
            self.ui_bridge._append_event({"type": "hand_tracking_state", "state": "OFF"})
        return True

    def toggle_hand_tracking(self):
        if self.active:
            return self.stop_hand_tracking()
        else:
            return self.start_hand_tracking()

    def is_hand_tracking_active(self):
        return self.active

    def _tracking_loop(self):
        self._tracking_stage = "camera initialization"
        try:
            self._tracking_loop_impl()
        except Exception:
            logger.exception("Hand tracking loop crashed (stage=%s)", self._tracking_stage)
            raise

    def _tracking_loop_impl(self):
        self._tracking_stage = "camera capture initialization"
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            logger.error("Could not open webcam.")
            self.active = False
            with self.gesture_lock:
                self.gesture_engine.reset()
            if self.ui_bridge:
                self.ui_bridge.set_hand_state({
                    "tracking": False, "hand": None, "x": 0.5, "y": 0.5,
                    "timestamp": time.time(), "hands": [], "fps": 0.0,
                })
                self.ui_bridge._append_event({"type": "sensor_status", "status": "error", "sensor": "hand_tracking", "reason": "camera_unavailable"})
                self.ui_bridge._append_event({"type": "hand_tracking_state", "state": "OFF"})
            return

        self._tracking_stage = "camera configuration"
        # Optimization 1: Reduce Resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        logger.info(f"Camera actual resolution: {actual_w}x{actual_h}")

        self.start_time = time.time()
        self.frame_count = 0

        # Profiling Metrics
        self.metrics = {
            "preprocess": 0.0,
            "inference": 0.0,
            "gesture": 0.0,
            "event": 0.0,
            "bridge": 0.0,
            "end_to_end": 0.0,
            "count": 0
        }
        self.last_metric_print = time.time()

        self.is_processing = False
        self.mp_timestamp_ms = 0
        self.preprocess_start_time = 0
        self.preprocess_end_time = 0
        self.preprocess_start_perf = 0.0
        self.preprocess_end_perf = 0.0
        self.process_stats = psutil.Process()
        self.process_stats.cpu_percent(None)

        self.metrics_lock = threading.Lock()
        self.state_lock = threading.Lock()

        self._tracking_stage = "MediaPipe initialization"
        BaseOptions = mp.tasks.BaseOptions
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path='data/hand_landmarker.task'),
            running_mode=VisionRunningMode.LIVE_STREAM,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            result_callback=self._on_result
        )

        self.cam_fps = 0
        self.cap_frames = 0
        self.cap_start_time = time.time()

        self.landmarker = HandLandmarker.create_from_options(options)

        try:
            failed_reads = 0
            while self.active and self.cap.isOpened():
                self._tracking_stage = "camera capture"
                success, frame = self.cap.read()
                if not success:
                    failed_reads += 1
                    if failed_reads >= 30:
                        logger.error("Webcam stopped returning frames; releasing hand interaction state.")
                        self.active = False
                        if self.ui_bridge:
                            self.ui_bridge.set_hand_state({
                                "tracking": False, "hand": None, "x": 0.5, "y": 0.5,
                                "timestamp": time.time(), "hands": [], "fps": round(self.fps, 1),
                            })
                            self.ui_bridge._append_event({
                                "type": "sensor_status", "status": "error",
                                "sensor": "hand_tracking", "reason": "camera_interrupted",
                            })
                            self.ui_bridge._append_event({"type": "hand_tracking_state", "state": "OFF"})
                        break
                    time.sleep(0.01)
                    continue
                failed_reads = 0

                self.cap_frames += 1
                curr_time = time.time()
                if curr_time - self.cap_start_time > 1.0:
                    self.cam_fps = self.cap_frames / (curr_time - self.cap_start_time)
                    self.cap_frames = 0
                    self.cap_start_time = curr_time

                with self.state_lock:
                    currently_processing = self.is_processing

                # Newest-frame-wins: skip frame if MediaPipe is still busy
                if not currently_processing:
                    with self.state_lock:
                        self.is_processing = True

                    t0 = time.time()
                    self.preprocess_start_time = t0
                    self.preprocess_start_perf = time.perf_counter()

                    self._tracking_stage = "frame preprocessing"
                    # Explicitly resize frame
                    image = cv2.resize(frame, (640, 480))
                    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)

                    self.preprocess_end_time = time.time()
                    self.preprocess_end_perf = time.perf_counter()

                    # Monotonically increasing timestamp required for LIVE_STREAM
                    self.mp_timestamp_ms += 33

                    self._tracking_stage = "MediaPipe detect_async submission"
                    self.landmarker.detect_async(mp_image, self.mp_timestamp_ms)
        finally:
            self._tracking_stage = "MediaPipe/camera cleanup"
            self.landmarker.close()
            if self.cap:
                self.cap.release()
                self.cap = None

    def _on_result(self, results: mp.tasks.vision.HandLandmarkerResult, output_image: mp.Image, timestamp_ms: int):
        callback_stage = "callback entry"
        try:
            callback_stage = "callback timing and metrics setup"
            callback_perf_start = time.perf_counter()
            t_start = self.preprocess_start_time
            t1 = self.preprocess_end_time
            current_time = time.time()

            # FPS Calculation
            with self.state_lock:
                self.frame_count += 1
                if current_time - self.start_time > 1.0:
                    self.fps = self.frame_count / (current_time - self.start_time)
                    self.start_time = current_time
                    self.frame_count = 0

            hands_data = []
            gesture_perf_start = time.perf_counter()

            if results.hand_landmarks:
                if not self.hand_present:
                    self.hand_present = True
                    callback_stage = "hand appeared event and bridge emission"
                    self._emit_event({"type": "hand", "event": "appeared", "hand": "unknown", "confidence": 1.0, "timestamp": current_time})

                for hand_idx, hand_landmarks in enumerate(results.hand_landmarks):
                    callback_stage = "landmark and handedness processing"
                    handedness = results.handedness[hand_idx][0]
                    label = handedness.category_name # "Left" or "Right"
                    score = handedness.score

                    # Convert landmarks for UI
                    pts = [{"x": round(lm.x, 4), "y": round(lm.y, 4), "z": round(lm.z, 4)} for lm in hand_landmarks]

                    hand_data = {
                        "hand": label.lower(),
                        "confidence": round(score, 2),
                        "gesture": "UNCLASSIFIED",
                        "landmarks": pts,
                    }
                    hands_data.append(hand_data)
            else:
                if self.hand_present:
                    self.hand_present = False
                    self._emit_event({"type": "hand", "event": "disappeared", "hand": "unknown", "confidence": 1.0, "timestamp": current_time})
                self.active_hand = None

            callback_stage = "gesture recognition"
            with self.gesture_lock:
                hands_data, semantic_events = self.gesture_engine.update(hands_data, current_time)
            gesture_perf_ms = (time.perf_counter() - gesture_perf_start) * 1000
            event_perf_start = time.perf_counter()
            for event in semantic_events:
                callback_stage = "gesture event emission and UI bridge delivery"
                self._emit_event(event)
                if self.event_callback:
                    callback_stage = "interaction controller event callback"
                    self.event_callback(event)
            event_perf_ms = (time.perf_counter() - event_perf_start) * 1000

            if current_time - self._last_gesture_diagnostic >= 1.0:
                detected_count = len(results.hand_landmarks or [])
                landmarks_present = detected_count > 0
                valid_inputs = [
                    hand for hand in hands_data
                    if len(hand.get("landmarks", [])) == 21
                    and hand.get("confidence", 0.0) >= self.gesture_engine.config["minimum_hand_confidence"]
                ]
                primary = valid_inputs[0] if valid_inputs else None
                primary_hand = primary.get("hand", "unknown") if primary else "unknown"
                raw_gesture = primary.get("classifier_output", "NOT_CLASSIFIED") if primary else "NOT_CLASSIFIED"
                gesture_state = primary.get("gesture_state", "IDLE") if primary else "IDLE"
                emitted = ",".join(
                    f"{event.get('gesture', event.get('type'))}:{event.get('phase', 'EVENT')}"
                    for event in semantic_events
                ) or "none"
                logger.info(
                    "GESTURE PIPELINE callback=YES hands=%d landmarks=%s primary=%s "
                    "gesture_input=%s raw=%s state=%s emitted=%s interaction_callback=%s",
                    detected_count,
                    "YES" if landmarks_present else "NO",
                    primary_hand,
                    "YES" if primary else "NO",
                    raw_gesture,
                    gesture_state,
                    emitted,
                    "YES" if self.event_callback and semantic_events else "NO",
                )
                self._last_gesture_diagnostic = current_time

            bridge_perf_start = time.perf_counter()
            if self.ui_bridge:
                callback_stage = "UI bridge latest-state update"
                selected_hand = next(
                    (hand for hand in hands_data if hand["hand"] == self.active_hand),
                    None,
                )
                if selected_hand is None and hands_data:
                    selected_hand = next(
                        (hand for hand in hands_data if hand["hand"] == "right"),
                        hands_data[0],
                    )
                    self.active_hand = selected_hand["hand"]
                for hand in hands_data:
                    hand["role"] = "primary" if hand["hand"] == self.active_hand else "secondary"
                self.ui_bridge.set_hand_state({
                    "tracking": bool(self.active),
                    "hand": selected_hand["hand"] if selected_hand else None,
                    # Webcam coordinates are mirrored relative to physical horizontal
                    # motion. Normalize once here; UI +X then remains screen-right.
                    "x": 1.0 - selected_hand["landmarks"][0]["x"] if selected_hand else 0.5,
                    "y": selected_hand["landmarks"][0]["y"] if selected_hand else 0.5,
                    "timestamp": current_time,
                    "hands": hands_data,
                    "fps": round(self.fps, 1),
                })
            bridge_perf_ms = (time.perf_counter() - bridge_perf_start) * 1000
            callback_perf_end = time.perf_counter()

            # Metrics Aggregation
            callback_stage = "performance metrics aggregation"
            with self.metrics_lock:
                self.metrics["preprocess"] += (t1 - t_start) * 1000
                self.metrics["inference"] += max(0.0, (callback_perf_start - self.preprocess_end_perf) * 1000)
                self.metrics["gesture"] += gesture_perf_ms
                self.metrics["event"] += event_perf_ms
                self.metrics["bridge"] += bridge_perf_ms
                self.metrics["end_to_end"] += max(
                    0.0, (callback_perf_end - self.preprocess_start_perf) * 1000
                )
                self.metrics["count"] += 1

                if current_time - self.last_metric_print > 3.0:
                    cnt = self.metrics["count"]
                    if cnt > 0:
                        cpu_percent = self.process_stats.cpu_percent(None)
                        ram_mb = self.process_stats.memory_info().rss / (1024 * 1024)
                        logger.info(f"--- PERFORMANCE METRICS ({cnt} frames) ---")
                        logger.info(f"Camera FPS: {getattr(self, 'cam_fps', 0):.1f}")
                        logger.info(f"Inference FPS: {self.fps:.1f}")
                        logger.info(f"Preprocess time: {self.metrics['preprocess']/cnt:.2f} ms")
                        logger.info(f"Inference time: {self.metrics['inference']/cnt:.2f} ms")
                        logger.info(f"Landmark/gesture processing: {self.metrics['gesture']/cnt:.2f} ms")
                        logger.info(f"Semantic event delivery: {self.metrics['event']/cnt:.2f} ms")
                        logger.info(f"Latest-state bridge update: {self.metrics['bridge']/cnt:.2f} ms")
                        logger.info(f"Capture-to-UI callback: {self.metrics['end_to_end']/cnt:.2f} ms")
                        logger.info(f"CPU usage: {cpu_percent:.1f}%")
                        logger.info(f"RAM usage: {ram_mb:.1f} MB")
                        logger.info("------------------------------------------")

                    self.metrics = {k: 0.0 for k in self.metrics if k != "count"}
                    self.metrics["count"] = 0
                    self.last_metric_print = current_time

        except Exception as exc:
            self.last_callback_failure = {
                "stage": callback_stage,
                "timestamp_ms": timestamp_ms,
                "exception": repr(exc),
            }
            logger.exception(
                "Hand tracking MediaPipe callback crashed (stage=%s, timestamp_ms=%s)",
                callback_stage,
                timestamp_ms,
            )
            raise
        finally:
            with self.state_lock:
                self.is_processing = False


    def _emit_event(self, event_data):
        if self.ui_bridge:
            self.ui_bridge._append_event(event_data)
        if event_data.get("type") != "hand_tracking_frame":
            logger.info(f"Emitted: {event_data}")

# Singleton instance
controller = HandTrackingController()

def start_hand_tracking(ui_bridge=None, event_callback=None):
    return controller.start_hand_tracking(ui_bridge, event_callback)

def stop_hand_tracking():
    return controller.stop_hand_tracking()

def toggle_hand_tracking(ui_bridge=None):
    if ui_bridge:
        controller.ui_bridge = ui_bridge
    return controller.toggle_hand_tracking()

def is_hand_tracking_active():
    return controller.is_hand_tracking_active()

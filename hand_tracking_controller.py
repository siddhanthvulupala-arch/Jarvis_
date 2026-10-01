import cv2
import mediapipe as mp
import time
import threading
import logging
import psutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HandTrackingController:
    def __init__(self, ui_bridge=None, event_callback=None):
        self.ui_bridge = ui_bridge
        self.event_callback = event_callback
        self.active = False
        self.thread = None
        self.cap = None
        
        # Debounce / State tracking
        self.last_event_time = 0
        self.event_cooldown = 1.0
        self.hand_present = False
        self.last_frame_emit_time = 0
        self.hand_history = {"left": [], "right": []}
        
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
        if ui_bridge:
            self.ui_bridge = ui_bridge
        if event_callback:
            self.event_callback = event_callback
            
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
        if self.thread:
            self.thread.join(timeout=2.0)
            
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
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            logger.error("Could not open webcam.")
            self.active = False
            if self.ui_bridge:
                self.ui_bridge._append_event({"type": "sensor_status", "status": "error", "sensor": "hand_tracking", "reason": "camera_unavailable"})
                self.ui_bridge._append_event({"type": "hand_tracking_state", "state": "OFF"})
            return
            
        # Optimization 1: Reduce Resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        logger.info(f"Camera actual resolution: {actual_w}x{actual_h}")
        
        # Optimization 2 & 3: Decoupled Camera Thread
        self.latest_frame = None
        self.new_frame_event = threading.Event()
        
        def capture_thread_func():
            self.cap_frames = 0
            self.cap_start_time = time.time()
            self.cam_fps = 0
            while self.active and self.cap.isOpened():
                success, frame = self.cap.read()
                if success:
                    self.latest_frame = frame
                    self.new_frame_event.set()
                    self.cap_frames += 1
                    
                    curr_time = time.time()
                    if curr_time - self.cap_start_time > 1.0:
                        self.cam_fps = self.cap_frames / (curr_time - self.cap_start_time)
                        self.cap_frames = 0
                        self.cap_start_time = curr_time
                else:
                    time.sleep(0.01)
                    
        cap_thread = threading.Thread(target=capture_thread_func, daemon=True)
        cap_thread.start()
            
        self.start_time = time.time()
        self.frame_count = 0
        
        # Profiling Metrics
        metrics = {
            "preprocess": 0.0,
            "inference": 0.0,
            "landmark": 0.0,
            "event": 0.0,
            "count": 0
        }
        last_metric_print = time.time()
        
        BaseOptions = mp.tasks.BaseOptions
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path='data/hand_landmarker.task'),
            running_mode=VisionRunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        with HandLandmarker.create_from_options(options) as landmarker:
            while self.active:
                if not self.new_frame_event.wait(timeout=0.1):
                    continue
                    
                t_start = time.time()
                
                image = self.latest_frame
                self.new_frame_event.clear()
                
                if image is None:
                    continue

                t0 = time.time()
                # Explicitly resize frame to reduce processing time, especially if the camera ignored the cap.set properties
                image = cv2.resize(image, (640, 480))
                rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
                timestamp_ms = int(time.time() * 1000)
                t1 = time.time()
                
                try:
                    results = landmarker.detect_for_video(mp_image, timestamp_ms)
                except Exception as e:
                    logger.error(f"Detection error: {e}")
                    time.sleep(0.01)
                    continue
                t2 = time.time()

                current_time = time.time()
                
                # FPS Calculation
                self.frame_count += 1
                if current_time - self.start_time > 1.0:
                    self.fps = self.frame_count / (current_time - self.start_time)
                    self.start_time = current_time
                    self.frame_count = 0
                
                gesture_text = ""
                confidence_text = ""
                hands_data = []
                
                if results.hand_landmarks:
                    if not self.hand_present:
                        self.hand_present = True
                        self._emit_event({"type": "hand", "event": "appeared", "hand": "unknown", "confidence": 1.0, "timestamp": current_time})
                        
                    for hand_idx, hand_landmarks in enumerate(results.hand_landmarks):
                        handedness = results.handedness[hand_idx][0]
                        label = handedness.category_name # "Left" or "Right"
                        score = handedness.score
                        
                        # Convert landmarks for UI
                        pts = [{"x": round(lm.x, 4), "y": round(lm.y, 4), "z": round(lm.z, 4)} for lm in hand_landmarks]
                        
                        wrist = hand_landmarks[0]
                        middle_tip = hand_landmarks[12]
                        thumb_tip = hand_landmarks[4]
                        index_tip = hand_landmarks[8]
                        dist = ((wrist.x - middle_tip.x)**2 + (wrist.y - middle_tip.y)**2)**0.5
                        pinch_dist = ((thumb_tip.x - index_tip.x)**2 + (thumb_tip.y - index_tip.y)**2)**0.5
                        
                        gesture = "point" # default fallback
                        if dist > 0.4:
                            gesture = "open_palm"
                        elif dist < 0.2:
                            gesture = "fist"
                        elif pinch_dist < 0.05:
                            gesture = "pinch"

                            
                        gesture_text = f"{label}: {gesture.upper()}"
                        confidence_text = f"{score*100:.0f}%"
                        
                        hands_data.append({
                            "hand": label.lower(),
                            "confidence": round(score, 2),
                            "gesture": gesture.upper(),
                            "landmarks": pts
                        })
                            
                        # Update history for swipe detection
                        hand_label_lower = label.lower()
                        self.hand_history[hand_label_lower].append((current_time, wrist.x, wrist.y))
                        # Keep only last 1 second
                        self.hand_history[hand_label_lower] = [h for h in self.hand_history[hand_label_lower] if current_time - h[0] < 1.0]
                        
                        swipe_event = None
                        if len(self.hand_history[hand_label_lower]) > 5:
                            old_t, old_x, old_y = self.hand_history[hand_label_lower][0]
                            dx = wrist.x - old_x
                            dy = wrist.y - old_y
                            dt = current_time - old_t
                            
                            if dt > 0.1:
                                vx = dx / dt
                                vy = dy / dt
                                speed_threshold = 1.5
                                if abs(vx) > speed_threshold or abs(vy) > speed_threshold:
                                    if abs(vx) > abs(vy):
                                        swipe_dir = "left" if vx < 0 else "right"
                                    else:
                                        swipe_dir = "up" if vy < 0 else "down"
                                    
                                    swipe_event = {
                                        "type": "motion",
                                        "direction": swipe_dir.upper(),
                                        "hand": hand_label_lower,
                                        "velocity": round(max(abs(vx), abs(vy)), 2),
                                        "source": "hand_sensor",
                                        "timestamp": current_time
                                    }
                                    self.hand_history[hand_label_lower].clear()

                        # Debounce gesture
                        if current_time - self.last_event_time > self.event_cooldown:
                            events_to_emit = []
                            if swipe_event:
                                events_to_emit.append(swipe_event)
                            else:
                                events_to_emit.append({
                                    "type": "gesture",
                                    "gesture": gesture,
                                    "hand": label.lower(),
                                    "confidence": round(score, 2),
                                    "timestamp": current_time,
                                    "source": "hand_sensor"
                                })
                            
                            for evt in events_to_emit:
                                self._emit_event(evt)
                                if self.event_callback:
                                    try:
                                        self.event_callback(evt)
                                    except Exception as e:
                                        logger.error(f"Event callback error: {e}")
                                        
                            self.last_event_time = current_time
                            
                else:
                    if self.hand_present:
                        self.hand_present = False
                        self._emit_event({"type": "hand", "event": "disappeared", "hand": "unknown", "confidence": 1.0, "timestamp": current_time})
                
                t3 = time.time()
                # Emit visualization frame to UI (Throttled to ~30 FPS)
                if current_time - self.last_frame_emit_time > 0.033:
                    if self.ui_bridge:
                        self.ui_bridge._append_event({
                            "type": "hand_tracking_frame",
                            "fps": round(self.fps, 1),
                            "hands": hands_data
                        })
                    self.last_frame_emit_time = current_time
                t4 = time.time()

                # Metrics Aggregation
                metrics["preprocess"] += (t1 - t0) * 1000
                metrics["inference"] += (t2 - t1) * 1000
                metrics["landmark"] += (t3 - t2) * 1000
                metrics["event"] += (t4 - t3) * 1000
                metrics["count"] += 1

                if current_time - last_metric_print > 3.0:
                    cnt = metrics["count"]
                    if cnt > 0:
                        process = psutil.Process()
                        cpu_percent = process.cpu_percent()
                        ram_mb = process.memory_info().rss / (1024 * 1024)
                        logger.info(f"--- PERFORMANCE METRICS ({cnt} frames) ---")
                        logger.info(f"Camera FPS: {getattr(self, 'cam_fps', 0):.1f}")
                        logger.info(f"Inference FPS: {self.fps:.1f}")
                        logger.info(f"Preprocess time: {metrics['preprocess']/cnt:.2f} ms")
                        logger.info(f"Inference time: {metrics['inference']/cnt:.2f} ms")
                        logger.info(f"Gesture processing: {metrics['landmark']/cnt:.2f} ms")
                        logger.info(f"UI transmission: {metrics['event']/cnt:.2f} ms")
                        logger.info(f"Total pipeline: {(t4-t_start)*1000:.2f} ms")
                        logger.info(f"CPU usage: {cpu_percent:.1f}%")
                        logger.info(f"RAM usage: {ram_mb:.1f} MB")
                        logger.info("------------------------------------------")
                    metrics = {k: 0.0 for k in metrics if k != "count"}
                    metrics["count"] = 0
                    last_metric_print = current_time
                
        # Cleanup
        if self.cap:
            self.cap.release()
            self.cap = None
            
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

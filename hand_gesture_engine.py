"""Lightweight gesture classification and per-hand gesture state tracking."""

from collections import deque
import math


DEFAULT_GESTURE_CONFIG = {
    "finger_open_threshold": 1.14,
    "finger_close_threshold": 1.08,
    "finger_smoothing": 0.60,
    "pinch_start_threshold": 0.055,
    "pinch_release_threshold": 0.075,
    "gesture_hysteresis_frames": 2,
    "point_hold_duration_seconds": 2.0,
    "point_hold_position_tolerance": 0.035,
    "air_tap_max_seconds": 0.75,
    "pinch_hold_seconds": 0.75,
    "air_tap_cooldown_seconds": 0.45,
    "minimum_hand_confidence": 0.50,
    "swipe_min_displacement": 0.14,
    "swipe_min_velocity": 0.70,
    "swipe_min_samples": 3,
    "swipe_window_seconds": 0.50,
    "swipe_direction_consistency": 0.85,
    "swipe_cooldown_seconds": 0.75,
    "swipe_rearm_displacement": 0.045,
    "swipe_rearm_velocity": 0.18,
}


class HandGestureEngine:
    """Classify existing poses and emit one-shot state transitions per hand."""

    FINGER_JOINTS = {
        "thumb": (4, 3), "index": (8, 6), "middle": (12, 10),
        "ring": (16, 14), "pinky": (20, 18),
    }

    def __init__(self, config=None):
        self.config = {**DEFAULT_GESTURE_CONFIG, **(config or {})}
        self.hands = {}

    def reset(self):
        self.hands.clear()

    def _state(self, hand):
        return self.hands.setdefault(hand, {
            "ratios": {}, "finger_states": {}, "pinching": False,
            "active": None, "pending": None, "pending_frames": 0,
            "history": deque(), "last_swipe": 0.0,
            "swipe_armed": True, "swipe_rearm_frames": 0,
            "swipe_rearm_anchor": None,
            "last_wrist": None,
            "point_pinch_started_at": None,
            "point_pinch_confidence": 0.0,
            "last_air_tap": float("-inf"),
            "point_hold_started_at": None,
            "point_hold_anchor": None,
            "point_hold_confidence": 0.0,
            "point_hold_active": False,
        })

    def _classify(self, hand, landmarks):
        state = self._state(hand)
        wrist = landmarks[0]
        ratios = {}
        fingers = {}
        alpha = self.config["finger_smoothing"]
        for finger, (tip_idx, pip_idx) in self.FINGER_JOINTS.items():
            tip, pip = landmarks[tip_idx], landmarks[pip_idx]
            ratio = math.hypot(tip["x"] - wrist["x"], tip["y"] - wrist["y"]) / max(
                math.hypot(pip["x"] - wrist["x"], pip["y"] - wrist["y"]), 1e-6
            )
            smoothed = state["ratios"].get(finger, ratio)
            smoothed += (ratio - smoothed) * alpha
            state["ratios"][finger] = smoothed
            was_open = state["finger_states"].get(finger, False)
            threshold = self.config["finger_close_threshold"] if was_open else self.config["finger_open_threshold"]
            fingers[finger] = smoothed > threshold
        state["finger_states"] = fingers

        thumb, index = landmarks[4], landmarks[8]
        pinch_distance = math.hypot(thumb["x"] - index["x"], thumb["y"] - index["y"])
        if state["pinching"]:
            state["pinching"] = pinch_distance <= self.config["pinch_release_threshold"]
        else:
            state["pinching"] = pinch_distance <= self.config["pinch_start_threshold"]

        extended = sum(fingers.values())
        if state["pinching"]:
            gesture = "PINCH"
        elif fingers["index"] and fingers["middle"] and not fingers["ring"] and not fingers["pinky"]:
            gesture = "TWO_FINGER"
        elif extended == 5:
            gesture = "OPEN_PALM"
        elif extended == 0:
            gesture = "FIST"
        elif fingers["index"] and not fingers["middle"] and not fingers["ring"] and not fingers["pinky"]:
            gesture = "POINT"
        else:
            gesture = None

        # Rule confidence reflects distance from the pose boundary; it is not
        # presented as a probability from a learned model.
        margins = [abs(value - 1.11) for value in state["ratios"].values()]
        confidence = 0.0 if gesture is None else min(1.0, 0.72 + (sum(margins) / max(len(margins), 1)) * 0.7)
        diagnostic = {
            "finger_states": fingers,
            "finger_ratios": {key: round(value, 3) for key, value in state["ratios"].items()},
            "thumb_index_distance": round(pinch_distance, 4),
            "classifier_output": gesture or "UNCLASSIFIED",
            "gesture_confidence": round(confidence, 3),
        }
        return gesture, confidence, diagnostic

    def _update_gesture_state(self, hand, candidate, confidence, timestamp):
        state = self._state(hand)
        required = self.config["gesture_hysteresis_frames"]
        if candidate == state["active"]:
            state["pending"] = None
            state["pending_frames"] = 0
            return state["active"], "HOLD" if state["active"] else "IDLE", []

        if candidate != state["pending"]:
            state["pending"] = candidate
            state["pending_frames"] = 1
        else:
            state["pending_frames"] += 1
        if state["pending_frames"] < required:
            return state["active"], "PENDING", []

        events = []
        previous = state["active"]
        if previous:
            events.append({"type": "gesture", "phase": "RELEASE", "gesture": previous,
                           "hand": hand, "timestamp": timestamp, "source": "hand_sensor"})
        state["active"] = candidate
        state["pending"] = None
        state["pending_frames"] = 0
        if candidate:
            events.append({"type": "gesture", "phase": "START", "gesture": candidate,
                           "hand": hand, "confidence": round(confidence, 3),
                           "timestamp": timestamp, "source": "hand_sensor"})
            return candidate, "START", events
        return None, "RELEASE" if previous else "IDLE", events

    def _update_point_hold(self, hand, state, active, candidate, confidence, landmarks,
                           timestamp, force_release=False):
        """Track a stable POINT dwell and emit one focus start/release pair."""
        events = []
        anchor = state["point_hold_anchor"]
        fingertip = landmarks[8] if landmarks and len(landmarks) == 21 else None
        tolerance = self.config["point_hold_position_tolerance"]
        moved_outside_target = bool(
            state["point_hold_active"] and anchor is not None and fingertip is not None
            and math.hypot(fingertip["x"] - anchor[0], fingertip["y"] - anchor[1]) > tolerance
        )
        # Pinch cancels immediately, before normal gesture hysteresis, so it
        # retains priority for the existing AIR_TAP and GRAB behavior.
        should_release = force_release or candidate == "PINCH" or active != "POINT" or moved_outside_target
        if state["point_hold_active"] and should_release:
            events.append({
                "type": "gesture", "gesture": "point_release", "phase": "RELEASE",
                "hand": hand, "confidence": round(state["point_hold_confidence"], 3),
                "timestamp": timestamp, "source": "hand_sensor",
            })
            state["point_hold_active"] = False
            state["point_hold_started_at"] = None
            state["point_hold_anchor"] = None
            state["point_hold_confidence"] = 0.0

        if candidate == "PINCH":
            state["point_hold_started_at"] = None
            state["point_hold_anchor"] = None
            state["point_hold_confidence"] = 0.0
            return events

        if force_release or active != "POINT" or fingertip is None:
            if not state["point_hold_active"]:
                state["point_hold_started_at"] = None
                state["point_hold_anchor"] = None
                state["point_hold_confidence"] = 0.0
            return events

        # Let the existing gesture hysteresis resolve a brief uncertain or
        # alternate pose before ending the hold. PINCH was handled immediately.
        if candidate != "POINT":
            return events

        if confidence < self.config["minimum_hand_confidence"]:
            if not state["point_hold_active"]:
                state["point_hold_started_at"] = None
                state["point_hold_anchor"] = None
                state["point_hold_confidence"] = 0.0
            return events

        if state["point_hold_active"]:
            return events

        if anchor is None or math.hypot(fingertip["x"] - anchor[0], fingertip["y"] - anchor[1]) > tolerance:
            state["point_hold_anchor"] = (fingertip["x"], fingertip["y"])
            state["point_hold_started_at"] = timestamp
            state["point_hold_confidence"] = confidence
            return events

        state["point_hold_confidence"] = min(state["point_hold_confidence"], confidence)
        if timestamp - state["point_hold_started_at"] >= self.config["point_hold_duration_seconds"]:
            state["point_hold_active"] = True
            events.append({
                "type": "gesture", "gesture": "point_hold", "phase": "START",
                "hand": hand, "confidence": round(state["point_hold_confidence"], 3),
                "timestamp": timestamp, "source": "hand_sensor",
            })
        return events

    def _swipe(self, hand, landmarks, timestamp, candidate_gesture, stable_gesture):
        state = self._state(hand)
        wrist = landmarks[0]
        x, y = 1.0 - wrist["x"], wrist["y"]  # match physical left/right mapping

        # Pinch manipulation and two-finger rotation own their motion. Clearing
        # the window here prevents their movement from becoming a later swipe.
        blocked_gestures = {"PINCH", "GRAB", "TWO_FINGER"}
        if candidate_gesture in blocked_gestures or stable_gesture in blocked_gestures:
            state["history"].clear()
            state["last_wrist"] = (timestamp, x, y)
            return None

        history = state["history"]
        history.append((timestamp, x, y))
        window = self.config["swipe_window_seconds"]
        while history and timestamp - history[0][0] > window:
            history.popleft()

        if len(history) < 2:
            state["last_wrist"] = (timestamp, x, y)
            return None
        previous_t, previous_x, previous_y = history[-2]
        recent_elapsed = max(timestamp - previous_t, 1e-6)
        recent_speed = math.hypot(x - previous_x, y - previous_y) / recent_elapsed

        if not state["swipe_armed"]:
            stationary = recent_speed <= self.config["swipe_rearm_velocity"]
            cooldown_complete = timestamp - state["last_swipe"] >= self.config["swipe_cooldown_seconds"]
            anchor = state["swipe_rearm_anchor"]
            remains_in_deadband = (
                anchor is not None
                and math.hypot(x - anchor[0], y - anchor[1]) <= self.config["swipe_rearm_displacement"]
            )
            if stationary and cooldown_complete:
                if remains_in_deadband:
                    state["swipe_rearm_frames"] += 1
                else:
                    state["swipe_rearm_anchor"] = (x, y)
                    state["swipe_rearm_frames"] = 1
                if state["swipe_rearm_frames"] >= 2:
                    state["swipe_armed"] = True
                    state["swipe_rearm_anchor"] = None
            else:
                state["swipe_rearm_anchor"] = None
                state["swipe_rearm_frames"] = 0
        swipe_vector = None
        samples = list(history)
        minimum_samples = self.config["swipe_min_samples"]
        for start_index in range(len(samples) - minimum_samples, -1, -1):
            old_t, old_x, old_y = samples[start_index]
            elapsed = timestamp - old_t
            if elapsed <= 0:
                continue
            dx, dy = x - old_x, y - old_y
            displacement = math.hypot(dx, dy)
            speed = displacement / elapsed
            if (elapsed <= window and
                    displacement >= self.config["swipe_min_displacement"] and
                    speed >= self.config["swipe_min_velocity"]):
                horizontal = abs(dx) >= abs(dy)
                axis_delta = dx if horizontal else dy
                direction_sign = 1 if axis_delta >= 0 else -1
                directional_steps = [
                    (samples[index + 1][1] - samples[index][1]) if horizontal else
                    (samples[index + 1][2] - samples[index][2])
                    for index in range(start_index, len(samples) - 1)
                ]
                forward = sum(max(direction_sign * step, 0.0) for step in directional_steps)
                reverse = sum(max(-direction_sign * step, 0.0) for step in directional_steps)
                consistency = forward / max(forward + reverse, 1e-6)
                if consistency < self.config["swipe_direction_consistency"]:
                    continue
                swipe_vector = (dx / elapsed, dy / elapsed, speed, displacement)
                break  # shortest qualifying window avoids stationary lead-in dilution
        if (state["swipe_armed"] and
                timestamp - state["last_swipe"] >= self.config["swipe_cooldown_seconds"] and
                swipe_vector is not None):
            vx, vy, speed, displacement = swipe_vector
            if abs(vx) >= abs(vy):
                direction = "LEFT" if vx < 0 else "RIGHT"
            else:
                direction = "UP" if vy < 0 else "DOWN"
            state["last_swipe"] = timestamp
            state["swipe_armed"] = False
            state["swipe_rearm_frames"] = 0
            state["swipe_rearm_anchor"] = None
            history.clear()
            return {"type": "swipe", "direction": direction, "gesture": f"SWIPE_{direction}", "hand": hand,
                    "velocity": round(speed, 3), "displacement": round(displacement, 3),
                    "timestamp": timestamp, "source": "hand_sensor"}
        state["last_wrist"] = (timestamp, x, y)
        return None

    def update(self, hands, timestamp):
        """Return enriched hands plus one-shot semantic events for this frame."""
        enriched = []
        events = []
        observed = set()
        for hand_data in hands:
            label = hand_data["hand"]
            landmarks = hand_data.get("landmarks") or []
            if len(landmarks) != 21 or hand_data.get("confidence", 0.0) < self.config["minimum_hand_confidence"]:
                continue
            observed.add(label)
            gesture, confidence, diagnostic = self._classify(label, landmarks)
            state = self._state(label)

            # A pinch that begins from a stable POINT is held pending until it
            # either releases quickly (one AIR_TAP) or crosses the grab hold
            # threshold. Keeping POINT active during the pending interval means
            # the UI's existing PINCH/grab path cannot acquire on a quick tap.
            pinch_started_at = state["point_pinch_started_at"]
            if state["active"] == "POINT" and gesture == "PINCH":
                if pinch_started_at is None:
                    pinch_started_at = timestamp
                    state["point_pinch_started_at"] = timestamp
                    state["point_pinch_confidence"] = confidence
                else:
                    state["point_pinch_confidence"] = max(state["point_pinch_confidence"], confidence)
                if timestamp - pinch_started_at < self.config["pinch_hold_seconds"]:
                    gesture_for_state = "POINT"
                else:
                    gesture_for_state = "PINCH"
            else:
                gesture_for_state = gesture

            if pinch_started_at is not None and gesture != "PINCH":
                pinch_duration = timestamp - pinch_started_at
                if (state["active"] == "POINT"
                        and pinch_duration < self.config["air_tap_max_seconds"]
                        and timestamp - state["last_air_tap"] >= self.config["air_tap_cooldown_seconds"]):
                    events.append({
                        "type": "gesture", "gesture": "AIR_TAP", "phase": "SELECT",
                        "hand": label, "confidence": round(state["point_pinch_confidence"], 3),
                        "timestamp": timestamp, "source": "hand_sensor",
                    })
                    state["last_air_tap"] = timestamp
                state["point_pinch_started_at"] = None
                state["point_pinch_confidence"] = 0.0

            if (gesture_for_state == "PINCH" and state["active"] == "POINT"
                    and state["pending"] != "PINCH"):
                # The elapsed hold is itself the pinch debounce; once met, let
                # the existing state transition fire on this callback.
                state["pending"] = "PINCH"
                state["pending_frames"] = self.config["gesture_hysteresis_frames"] - 1
            active, phase, transitions = self._update_gesture_state(label, gesture_for_state, confidence, timestamp)
            events.extend(transitions)
            events.extend(self._update_point_hold(
                label, state, active, gesture, confidence, landmarks, timestamp,
            ))
            swipe = self._swipe(label, landmarks, timestamp, gesture, active)
            if swipe:
                events.append(swipe)
            hand_data.update(diagnostic)
            hand_data["gesture"] = active or "UNCLASSIFIED"
            hand_data["gesture_confidence"] = confidence if active else 0.0
            hand_data["gesture_phase"] = phase
            hand_data["gesture_state"] = active or "IDLE"
            enriched.append(hand_data)

        for label, state in list(self.hands.items()):
            if label in observed or state["active"] is None:
                continue
            _, _, transitions = self._update_gesture_state(label, None, 0.0, timestamp)
            events.extend(transitions)
            events.extend(self._update_point_hold(
                label, state, state["active"], None, 0.0, None, timestamp,
                force_release=True,
            ))
            state["history"].clear()
            if state["active"] is None and state["pending"] is None:
                self.hands.pop(label, None)
        return enriched, events

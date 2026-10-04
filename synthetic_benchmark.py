import cv2
import mediapipe as mp
import time
import numpy as np
import psutil
import os

print("Starting synthetic hand tracking benchmark...")

# Setup Mediapipe using exact JARVIS configuration
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
landmarker = HandLandmarker.create_from_options(options)

artifact_dir = os.path.join(os.environ.get('USERPROFILE', ''), '.gemini', 'antigravity-ide', 'brain', 'a4a61626-3b83-46d4-ad2e-a7e6b4dc1d2f')

# Load the test images
img_0 = cv2.imread(os.path.join(artifact_dir, 'no_hands_1790870288946.jpg'))
img_1 = cv2.imread(os.path.join(artifact_dir, 'one_hand_1790870301776.jpg'))
img_2 = cv2.imread(os.path.join(artifact_dir, 'two_hands_1790870337947.jpg'))

if img_0 is None or img_1 is None or img_2 is None:
    print("Failed to load test images.")
    exit(1)

def profile_condition(name, base_img, simulate_motion=False, duration=3.0):
    print(f"\n--- Profiling Condition: {name} ---")
    
    frames = 0
    total_pre = 0
    total_inf = 0
    start_time = time.time()
    
    while time.time() - start_time < duration:
        frame = base_img.copy()
        
        if simulate_motion:
            # Shift image slightly to simulate motion
            shift_x = int(20 * np.sin(time.time() * 5))
            shift_y = int(20 * np.cos(time.time() * 5))
            M = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
            frame = cv2.warpAffine(frame, M, (frame.shape[1], frame.shape[0]))
        
        t0 = time.time()
        
        # Preprocessing exactly as in hand_tracking_controller.py
        frame = cv2.resize(frame, (640, 480))
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        timestamp_ms = int(time.time() * 1000)
        
        t1 = time.time()
        
        try:
            results = landmarker.detect_for_video(mp_image, timestamp_ms)
        except Exception as e:
            pass # Skip timestamp errors
            
        t2 = time.time()
        
        total_pre += (t1 - t0)
        total_inf += (t2 - t1)
        frames += 1

    process = psutil.Process()
    cpu_percent = process.cpu_percent()
    ram_mb = process.memory_info().rss / (1024 * 1024)
    
    effective_fps = frames / duration
    avg_pre = (total_pre / frames) * 1000 if frames > 0 else 0
    avg_inf = (total_inf / frames) * 1000 if frames > 0 else 0
    total_loop = avg_pre + avg_inf
    
    print(f"Condition: {name}")
    print(f"Effective FPS: {effective_fps:.1f}")
    print(f"Avg Preprocessing: {avg_pre:.2f} ms")
    print(f"Avg Inference: {avg_inf:.2f} ms")
    print(f"Total Tracker Loop: {total_loop:.2f} ms")
    print(f"CPU Utilization: {cpu_percent:.1f}%")
    print(f"RAM Usage: {ram_mb:.1f} MB")
    
    return effective_fps, total_loop

# Run profiles
profile_condition("A. No hands visible", img_0, simulate_motion=False)
profile_condition("B. One stationary hand", img_1, simulate_motion=False)
profile_condition("C. One moving hand", img_1, simulate_motion=True)
profile_condition("D. Two hands visible", img_2, simulate_motion=True) # Usually two hands implies some motion

print("\nProfiling Complete.")

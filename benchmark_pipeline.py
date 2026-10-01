import time
import cv2
import mediapipe as mp
import psutil
import os

print("Starting hand tracking benchmark...")
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("Failed to open webcam.")
    exit(1)

# Optimization 1: Reduce Resolution
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
print(f"Webcam actual resolution: {actual_w}x{actual_h}")

# Stage A: Camera Capture Only
print("\n--- Stage A: Camera Capture Only ---")
start_time = time.time()
frames = 0
while time.time() - start_time < 3:
    ret, frame = cap.read()
    if ret: frames += 1
print(f"Camera FPS: {frames / 3:.1f}")

# Setup Mediapipe
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path='data/hand_landmarker.task'),
    running_mode=VisionRunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
landmarker = HandLandmarker.create_from_options(options)

# Stage B: Camera + Preprocess + Inference
print("\n--- Stage B: Camera + Preprocess + Inference ---")
start_time = time.time()
frames = 0
total_pre = 0
total_inf = 0
while time.time() - start_time < 3:
    ret, frame = cap.read()
    if not ret: continue
    
    t0 = time.time()
    # PREPROCESS: Resize first! (Optimization attempt)
    # frame_resized = cv2.resize(frame, (320, 240)) # Testing if resizing helps
    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
    t1 = time.time()
    
    try:
        results = landmarker.detect_for_video(mp_image, int(time.time() * 1000))
    except Exception:
        pass
    t2 = time.time()
    
    total_pre += (t1-t0)*1000
    total_inf += (t2-t1)*1000
    frames += 1

if frames > 0:
    print(f"Pipeline B FPS: {frames / 3:.1f}")
    print(f"Average Preprocess: {total_pre/frames:.1f} ms")
    print(f"Average Inference: {total_inf/frames:.1f} ms")

cap.release()
print("\nBenchmark complete.")

# Checks camera indices 0-4 and reports which ones deliver a real image.
# Usage: python camera_check.py
import time

import cv2

print("Checking cameras... (this takes a few seconds)\n")
found = []
for idx in range(5):
    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        print(f"  index {idx}: not available")
        continue

    # Give the camera up to ~3 s to warm up and adjust exposure
    frame, brightness, t0 = None, 0.0, time.time()
    while time.time() - t0 < 3:
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
            brightness = float(f.mean())
            if brightness > 10:
                break
        time.sleep(0.03)
    cap.release()

    if frame is None:
        print(f"  index {idx}: opens, but sends no frames")
        continue

    h, w = frame.shape[:2]
    status = "BLACK image" if brightness <= 10 else "OK - real image"
    print(f"  index {idx}: {w}x{h}, brightness {brightness:5.1f}  -> {status}")
    if brightness > 10:
        found.append(idx)
        cv2.imwrite(f"camera_{idx}.jpg", frame)

print()
if found:
    print(f"Working camera(s): {found}  (snapshots saved as camera_<index>.jpg)")
    print(f"Start the tracker with:  python color_ball_tracking.py --source {found[0]}")
    if len(found) >= 2:
        print(f"Two cameras (depth):     python multicam_ball_tracking.py --source {found[0]} --side {found[1]}")
        print("  (check camera_<index>.jpg to see which one is the front and which the side camera)")
else:
    print("No camera delivered a real image. Check:")
    print("  - System Settings > Privacy & Security > Camera: allow your Terminal app, then restart it")
    print("  - Lid open / lens not covered / external webcam's privacy shutter open")
    print("  - Quit other apps using the camera (Zoom, FaceTime, Teams, OBS...)")

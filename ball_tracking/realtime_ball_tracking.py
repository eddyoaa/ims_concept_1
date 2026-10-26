# ============================================================
# REAL-TIME BALL TRACKING  (YOLO + Kalman filter)
# ============================================================
# Live version of linear_interpolation_ball_tracking.py.
#
# Differences from the original:
#   - Works frame by frame on a live source (webcam) or a video file.
#     No first pass over the whole video, no cache.
#   - Missing detections are PREDICTED from the last known position
#     and velocity (Kalman filter) instead of interpolated afterwards.
#     Prediction only needs the past, so it works live.
#
# Marker colors:
#   GREEN = ball detected by YOLO in this frame
#   RED   = ball not detected, position predicted by the Kalman filter
#
# Usage:
#   python realtime_ball_tracking.py                  # default webcam
#   python realtime_ball_tracking.py --source 1       # other camera
#   python realtime_ball_tracking.py --source ball.mp4
#   python realtime_ball_tracking.py --model best.pt --cls 0   # custom model
#   python realtime_ball_tracking.py --source ball.mp4 --roi 0,200,1280,720 --save out.mp4
#
# Press 'q' or ESC to quit.
# ============================================================

import argparse
import time

import cv2
import numpy as np
import torch
from ultralytics import YOLO


# ============================================================
# SETTINGS (command line)
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(description="Real-time ball tracking with YOLO + Kalman filter")
    p.add_argument("--source", default="0",
                   help="Camera index (0, 1, ...) or path to a video file. Default: 0 (webcam)")
    p.add_argument("--model", default="yolov8n.pt",
                   help="YOLO model. yolov8n.pt is downloaded automatically. Default: yolov8n.pt")
    p.add_argument("--cls", type=int, default=32,
                   help="Class ID of the ball. 32 = 'sports ball' in stock COCO models. "
                        "Use 0 for the tutorial's custom best.pt. Default: 32")
    p.add_argument("--conf", type=float, default=0.1,
                   help="Detection confidence threshold. Low, because small balls get low scores; "
                        "the tracker filters out stray detections. Default: 0.1")
    p.add_argument("--imgsz", type=int, default=1280,
                   help="YOLO input size. 1280 finds small/far balls; 640 is ~3x faster "
                        "and fine when the ball is big in the image. Default: 1280")
    p.add_argument("--device", default="auto", help="auto, mps, cuda, or cpu")
    p.add_argument("--max-missed", type=int, default=15,
                   help="Frames to keep predicting without a detection before the track is dropped")
    p.add_argument("--width", type=int, default=1280, help="Display / processing width")
    p.add_argument("--height", type=int, default=720, help="Display / processing height")
    p.add_argument("--switch-conf", type=float, default=0.2,
                   help="A detection away from the current track at least this confident "
                        "(and more confident than the track) makes the tracker jump to it. "
                        "Stops it from getting stuck on a false positive. Default: 0.2")
    p.add_argument("--roi", default=None,
                   help="Only accept detections inside this area: x1,y1,x2,y2 in display pixels "
                        "(e.g. 0,200,1280,720 ignores the top 200 px). Default: whole frame")
    p.add_argument("--save", default=None, help="Also write the annotated video to this file (.mp4)")
    p.add_argument("--no-show", action="store_true", help="Run without a window (for testing)")
    return p.parse_args()


def pick_device(requested):
    if requested != "auto":
        return requested
    if torch.backends.mps.is_available():
        return "mps"      # Apple Silicon GPU
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


# ============================================================
# KALMAN FILTER
# ============================================================
# State:       [x, y, vx, vy]   (pixels, pixels per second)
# Measurement: [x, y]           (ball center from YOLO)
# Model: constant velocity, with random acceleration as noise.
# That noise lets the filter follow throws, bounces and gravity.

class BallKalman:
    def __init__(self, accel_noise=3000.0, meas_noise=4.0):
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0],
                                              [0, 1, 0, 0]], np.float32)
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * meas_noise ** 2
        self.accel_noise = accel_noise
        self.initialized = False

    def init(self, x, y):
        self.kf.statePost = np.array([[x], [y], [0], [0]], np.float32)
        self.kf.errorCovPost = np.diag([25, 25, 1e5, 1e5]).astype(np.float32)
        self.initialized = True

    def predict(self, dt):
        # Time step can change from frame to frame (live cameras jitter),
        # so the matrices are rebuilt with the real dt each time.
        self.kf.transitionMatrix = np.array([[1, 0, dt, 0],
                                             [0, 1, 0, dt],
                                             [0, 0, 1, 0],
                                             [0, 0, 0, 1]], np.float32)
        q = self.accel_noise ** 2
        dt2, dt3, dt4 = dt * dt, dt ** 3, dt ** 4
        self.kf.processNoiseCov = (q * np.array([[dt4 / 4, 0, dt3 / 2, 0],
                                                 [0, dt4 / 4, 0, dt3 / 2],
                                                 [dt3 / 2, 0, dt2, 0],
                                                 [0, dt3 / 2, 0, dt2]])).astype(np.float32)
        s = self.kf.predict()
        return float(s[0, 0]), float(s[1, 0])

    def correct(self, x, y):
        s = self.kf.correct(np.array([[x], [y]], np.float32))
        return float(s[0, 0]), float(s[1, 0])

    @property
    def velocity(self):
        s = self.kf.statePost
        return float(s[2, 0]), float(s[3, 0])


# ============================================================
# HOOK FOR YOUR OWN CODE
# ============================================================

def on_ball(frame_idx, x, y, vx, vy, detected):
    """Called once per frame while a ball is being tracked.

    x, y   : ball center in pixels
    vx, vy : velocity in pixels per second (vy > 0 = moving down)
    detected: True if YOLO saw the ball this frame, False if predicted

    Put your own logic here, e.g. send OSC/MIDI, trigger a sound
    when the ball changes direction, etc.
    """
    pass


# ============================================================
# DRAWING
# ============================================================

def draw_marker(frame, x, y, color):
    x, y = int(round(x)), int(round(y))
    pts = np.array([[x, y - 10], [x + 8, y - 25], [x - 8, y - 25]], np.int32)
    cv2.fillPoly(frame, [pts], color)
    cv2.polylines(frame, [pts], True, (0, 0, 0), 1)


def draw_trail(frame, trail):
    for i in range(1, len(trail)):
        (x0, y0, d0), (x1, y1, _) = trail[i - 1], trail[i]
        color = (0, 255, 0) if d0 else (0, 0, 255)
        cv2.line(frame, (int(x0), int(y0)), (int(x1), int(y1)), color, 2)


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    args = parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    is_camera = isinstance(source, int)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source}")

    device = pick_device(args.device)
    print(f"Model: {args.model} | ball class: {args.cls} | device: {device}")
    model = YOLO(args.model)

    # Video files: use their frame rate for dt. Cameras: use the real clock.
    file_fps = cap.get(cv2.CAP_PROP_FPS) if not is_camera else 0
    file_dt = 1.0 / file_fps if file_fps and file_fps > 0 else 1 / 30

    roi = tuple(int(v) for v in args.roi.split(",")) if args.roi else None

    writer = None
    if args.save:
        out_fps = file_fps if file_fps and file_fps > 0 else 30
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), out_fps,
                                 (args.width, args.height))

    tracker = BallKalman()
    track_conf = 0.0           # running average confidence of the current track
    missed = 0
    trail = []                 # recent (x, y, detected) points
    frame_idx = 0
    last_t = time.perf_counter()
    fps_smooth = 0.0
    n_det = n_pred = 0

    cam_fails = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            # Cameras (esp. on macOS) often return a few empty frames while
            # starting up. Keep trying for a few seconds before giving up.
            if is_camera and cam_fails < 150:
                cam_fails += 1
                time.sleep(0.02)
                continue
            if is_camera and frame_idx == 0:
                print("\nNo image from the camera. Most likely:\n"
                      "  1. Camera permission: System Settings > Privacy & Security > Camera\n"
                      "     -> allow your Terminal app (or VS Code/iTerm), then restart it.\n"
                      "  2. Wrong camera: try --source 1 (index 0 can be an iPhone via Continuity Camera).\n"
                      "  3. Another app is using the camera (Zoom, FaceTime, Photo Booth...).")
            break
        cam_fails = 0
        frame = cv2.resize(frame, (args.width, args.height))

        now = time.perf_counter()
        loop_dt = now - last_t
        last_t = now
        dt = loop_dt if is_camera else file_dt
        dt = min(max(dt, 1e-3), 0.2)

        # ---- 1. Detect -------------------------------------------------
        results = model.predict(frame, imgsz=args.imgsz, conf=args.conf,
                                classes=[args.cls], device=device, verbose=False)
        boxes = results[0].boxes
        candidates = []        # (x, y, conf)
        if boxes is not None and len(boxes):
            xywh = boxes.xywh.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            for (bx, by, _, _), c in zip(xywh, confs):
                if roi and not (roi[0] <= bx <= roi[2] and roi[1] <= by <= roi[3]):
                    continue
                candidates.append((float(bx), float(by), float(c)))

        # ---- 2. Predict ------------------------------------------------
        pred = tracker.predict(dt) if tracker.initialized else None

        # ---- 3. Pick the detection that belongs to our track -----------
        measurement = None     # (x, y, conf)
        reinit = False
        if candidates:
            if pred is None:
                # No track yet: take the most confident ball
                measurement = max(candidates, key=lambda c: c[2])
                reinit = True
            else:
                # Split detections into those near where we expect the ball
                # (inside the gate) and the rest. The gate grows with speed
                # and with how long we've been blind.
                vx, vy = tracker.velocity
                speed = (vx * vx + vy * vy) ** 0.5
                gate = 120 + speed * dt * 2 + missed * 20
                dist = lambda c: ((c[0] - pred[0]) ** 2 + (c[1] - pred[1]) ** 2) ** 0.5
                inside = [c for c in candidates if dist(c) <= gate]
                outside = [c for c in candidates if dist(c) > gate]
                best_out = max(outside, key=lambda c: c[2]) if outside else None

                if best_out and best_out[2] >= args.switch_conf and best_out[2] > track_conf \
                        and (not inside or best_out[2] > max(c[2] for c in inside) + 0.1):
                    # A clearly better ball elsewhere: we were probably
                    # following a false positive. Jump to it.
                    measurement = best_out
                    reinit = True
                elif inside:
                    measurement = min(inside, key=dist)

        # ---- 4. Update -------------------------------------------------
        detected = False
        pos = None
        if measurement is not None:
            mx, my, mconf = measurement
            if reinit:
                tracker.init(mx, my)
                pos = (mx, my)
                track_conf = mconf
                trail.clear()
            else:
                pos = tracker.correct(mx, my)
                track_conf = 0.8 * track_conf + 0.2 * mconf
            missed = 0
            detected = True
        elif tracker.initialized:
            missed += 1
            if missed > args.max_missed:
                tracker.initialized = False   # lost it, wait for a new detection
                trail.clear()
            else:
                pos = pred

        # ---- 5. Output -------------------------------------------------
        if pos is not None:
            n_det += detected
            n_pred += not detected
            vx, vy = tracker.velocity
            on_ball(frame_idx, pos[0], pos[1], vx, vy, detected)
            trail.append((pos[0], pos[1], detected))
            trail = trail[-30:]

        fps_now = 1.0 / loop_dt if loop_dt > 0 else 0
        fps_smooth = fps_now if fps_smooth == 0 else 0.9 * fps_smooth + 0.1 * fps_now

        if not args.no_show or writer:
            if roi:
                cv2.rectangle(frame, roi[:2], roi[2:], (255, 200, 0), 1)
            draw_trail(frame, trail)
            if pos is not None:
                draw_marker(frame, pos[0], pos[1], (0, 255, 0) if detected else (0, 0, 255))
            status = "detected" if detected else ("predicted" if pos is not None else "searching")
            cv2.putText(frame, f"{fps_smooth:5.1f} FPS | {status}", (15, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        if writer:
            writer.write(frame)

        if not args.no_show:
            cv2.imshow("Real-Time Ball Tracking", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
        elif frame_idx % 50 == 0:
            p = f"({pos[0]:.0f}, {pos[1]:.0f})" if pos else "-"
            print(f"frame {frame_idx:5d} | {fps_smooth:5.1f} FPS | "
                  f"{'det ' if detected else 'pred' if pos else '----'} {p}")

        frame_idx += 1

    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    print(f"Done. {frame_idx} frames | ball detected in {n_det}, predicted in {n_pred}, "
          f"lost in {frame_idx - n_det - n_pred}")


if __name__ == "__main__":
    main()

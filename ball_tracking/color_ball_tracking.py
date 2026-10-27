# ============================================================
# REAL-TIME BALL TRACKING BY COLOR  (OpenCV HSV mask + Kalman filter)
# ============================================================
# No YOLO, no training, no GPU. Finds the ball by its color.
# Default color: green. Works best with a bright, saturated ball
# (neon green, pink, orange) and a background without that color.
#
# Usage:
#   python color_ball_tracking.py --source 1
#   python color_ball_tracking.py --source 1 --version 2
#   python color_ball_tracking.py --source ball.mp4
#
# Keys / mouse in the window:
#   1 / 2 / 3          -> switch detection version live (also the slider on top)
#   CLICK on the ball  -> use that exact color (auto-calibration)
#   m                  -> show/hide the mask window with sliders + debug view
#   s                  -> save current color settings (color_settings.json)
#   r                  -> reset to default green
#   q / ESC            -> quit
#
# Versions:
#   v1  color only. Every roughly round green blob counts.
#   v2  + shape filter: no corners (posters, tape, boxes), no ragged outline
#       (plants, clothes), not too stretched. Lenient near the predicted
#       position so a fast, motion-blurred ball isn't lost; balls cut off
#       by the image border (flying in) only need to be solid.
#   v3  + hand occlusion: a circle is fitted to the visible round edge only
#       (RANSAC), so a ball partly covered by a hand or split by fingers is
#       still found, with its TRUE center and radius. If the ball disappears
#       while moving slowly (held in a hand), its position is kept for a
#       while ("hidden") instead of being dropped.
#
# Sound (ball_sound.py), exactly two notes:
#   ball moves right (x grows)   -> G4      speed -> volume (still ball = silent)
#   ball moves left  (x shrinks) -> A4      y     -> low-pass filter (top bright, bottom dull)
#   x, y, velocity, note, volume and filter are shown as numbers in the window.
#   --no-audio: no sound. --audio-out test.wav: write the sound in sync with
#   the video instead of playing it (for testing with video files).
#
# Marker colors:
#   GREEN  = ball fully visible
#   CYAN   = ball partly hidden, center estimated from its visible edge (v3)
#   RED    = not visible, position predicted from its motion (Kalman filter)
#   ORANGE = not visible, probably held in a hand (v3)
# ============================================================

import argparse
import json
import os
import time

import cv2
import numpy as np

from ball_sound import BallSound

SETTINGS_FILE = "color_settings.json"
WINDOW = "Color Ball Tracking"

# HSV ranges in OpenCV: H 0-179, S 0-255, V 0-255
DEFAULT_GREEN = {"h_min": 35, "h_max": 85, "s_min": 80, "s_max": 255, "v_min": 40, "v_max": 255,
                 "strictness": 70}   # strictness in percent (slider)

VERSION_NAMES = {1: "v1 color only", 2: "v2 shape filter", 3: "v3 + hand occlusion"}

COL_DETECTED = (0, 255, 0)
COL_PARTIAL = (255, 255, 0)
COL_PREDICTED = (0, 0, 255)
COL_HIDDEN = (0, 165, 255)


# ============================================================
# SETTINGS (command line)
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(description="Real-time ball tracking by color")
    p.add_argument("--source", default="0", help="Camera index (0, 1, ...) or video file. Default: 0")
    p.add_argument("--version", type=int, default=3, choices=[1, 2, 3],
                   help="Detection version to start with (switch live with keys 1/2/3). Default: 3")
    p.add_argument("--min-radius", type=float, default=4, help="Ignore blobs smaller than this (px)")
    p.add_argument("--strictness", type=float, default=None,
                   help="0..1, how strictly blobs must look like a ball (v2/v3). Higher = fewer "
                        "false detections, but blurred/partly hidden balls may be missed. "
                        "Default: 0.7 (or the saved value)")
    p.add_argument("--max-missed", type=int, default=15,
                   help="Frames to keep predicting a flying ball without seeing it. Default: 15")
    p.add_argument("--hold-seconds", type=float, default=2.0,
                   help="v3: how long to keep a slow ball that disappeared (held in a hand). Default: 2")
    p.add_argument("--width", type=int, default=1280, help="Processing width")
    p.add_argument("--height", type=int, default=720, help="Processing height")
    p.add_argument("--save", default=None, help="Also write the annotated video to this file (.mp4)")
    p.add_argument("--mirror", action="store_true",
                   help="Mirror the image (selfie view), so 'right' on screen is your right")
    p.add_argument("--no-audio", action="store_true", help="No sound")
    p.add_argument("--audio-device", default=None, help="sounddevice output device (name or number)")
    p.add_argument("--audio-out", default=None,
                   help="Write the sound to this .wav in sync with the frames instead of playing it")
    p.add_argument("--max-speed", type=float, default=1500.0,
                   help="Ball speed in px/s that gives full volume. Default: 1500")
    p.add_argument("--no-show", action="store_true", help="Run without a window (for testing)")
    return p.parse_args()


# ============================================================
# KALMAN FILTER  (same as in realtime_ball_tracking.py)
# ============================================================
# State: [x, y, vx, vy] (pixels, pixels/second). Constant velocity
# with random acceleration as noise, so it follows throws and bounces.

class BallKalman:
    def __init__(self, accel_noise=3000.0, meas_noise=3.0):
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * meas_noise ** 2
        self.accel_noise = accel_noise
        self.initialized = False

    def init(self, x, y):
        self.kf.statePost = np.array([[x], [y], [0], [0]], np.float32)
        self.kf.errorCovPost = np.diag([25, 25, 1e5, 1e5]).astype(np.float32)
        self.initialized = True

    def predict(self, dt):
        self.kf.transitionMatrix = np.array([[1, 0, dt, 0], [0, 1, 0, dt],
                                             [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
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

    def damp_velocity(self, factor):
        s = self.kf.statePost.copy()
        s[2:4] *= factor
        self.kf.statePost = s

    @property
    def velocity(self):
        s = self.kf.statePost
        return float(s[2, 0]), float(s[3, 0])


# ============================================================
# HOOK FOR YOUR OWN CODE
# ============================================================

def on_ball(frame_idx, x, y, radius, vx, vy, detected):
    """Called once per frame while the ball is tracked.

    x, y    : ball center in pixels
    radius  : apparent size in pixels (bigger = closer to the camera)
    vx, vy  : velocity in pixels/second (vy > 0 = moving down)
    detected: True if seen this frame (fully or partly), False if predicted/hidden

    Put your own logic here: send OSC/MIDI, play a sound when the
    ball changes direction (sign of vy flips = bounce / top of throw), ...
    """
    pass


# ============================================================
# COLOR SETTINGS
# ============================================================

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                s = json.load(f)
            print(f"Loaded color settings from {SETTINGS_FILE}: {s}")
            return {**DEFAULT_GREEN, **s}
        except Exception as e:
            print(f"Could not read {SETTINGS_FILE} ({e}), using default green")
    return dict(DEFAULT_GREEN)


def save_settings(s):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)
    print(f"Saved color settings to {SETTINGS_FILE}: {s}")


def settings_from_click(hsv, x, y):
    """Take the median color around the clicked point and build a range around it."""
    h_img, w_img = hsv.shape[:2]
    x0, x1 = max(0, x - 4), min(w_img, x + 5)
    y0, y1 = max(0, y - 4), min(h_img, y + 5)
    patch = hsv[y0:y1, x0:x1].reshape(-1, 3)
    h, s, v = np.median(patch, axis=0)
    return {
        "h_min": int(max(0, h - 12)), "h_max": int(min(179, h + 12)),
        "s_min": int(max(40, s - 70)), "s_max": 255,
        "v_min": int(max(25, v - 80)), "v_max": 255,
    }   # strictness is kept by the caller


SLIDERS = [("H min", "h_min", 179), ("H max", "h_max", 179),
           ("S min", "s_min", 255), ("S max", "s_max", 255),
           ("V min", "v_min", 255), ("V max", "v_max", 255),
           ("Strictness %", "strictness", 100)]


def create_mask_window(settings):
    cv2.namedWindow("Mask", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Mask", 640, 480)
    for label, key, mx in SLIDERS:
        cv2.createTrackbar(label, "Mask", settings[key], mx, lambda v: None)


def read_sliders(settings):
    for label, key, _ in SLIDERS:
        settings[key] = cv2.getTrackbarPos(label, "Mask")


def write_sliders(settings):
    for label, key, _ in SLIDERS:
        cv2.setTrackbarPos(label, "Mask", settings[key])


# ============================================================
# DETECTION: color mask + blob measurements
# ============================================================

KERNELS = {
    1: (cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))),
    2: (cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))),
}
KERNELS[3] = KERNELS[2]


def make_mask(hsv, s, version):
    lo = np.array([s["h_min"], s["s_min"], s["v_min"]], np.uint8)
    hi = np.array([s["h_max"], s["s_max"], s["v_max"]], np.uint8)
    mask = cv2.inRange(hsv, lo, hi)
    open_k, close_k = KERNELS[version]
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_k)    # remove speckles
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_k)  # fill highlights / small holes
    return mask


def measure(points, area, w_img, h_img):
    """Shape features of a blob (or a group of blob pieces) from its outline points."""
    (x, y), r = cv2.minEnclosingCircle(points)
    hull_area = cv2.contourArea(cv2.convexHull(points))
    (_, _), (rw, rh), _ = cv2.minAreaRect(points)
    bx, by, bw, bh = cv2.boundingRect(points)
    return {
        "x": x, "y": y, "r": r, "area": area, "points": points,
        # ball ~1.0, plants / ragged things / hand-covered ball lower
        "solidity": area / hull_area if hull_area > 0 else 0,
        # how much of its tightest rectangle the blob fills:
        # ball ~0.78, motion-blurred ball 0.84-0.92, rectangles ~1.0, triangles ~0.5
        "rect_fill": area / (rw * rh) if rw * rh > 0 else 1,
        # 1 = round, motion blur stretches the ball to ~1.5-2.5
        "aspect": max(rw, rh) / max(min(rw, rh), 1e-3),
        # ball diameter; unlike the length, motion blur doesn't change it
        "width": min(rw, rh),
        # cut off by the image border (e.g. ball flying in)
        "border": bx <= 2 or by <= 2 or bx + bw >= w_img - 2 or by + bh >= h_img - 2,
        "kind": "full", "reason": "", "near": False,
    }


def find_blobs(mask, min_radius):
    h_img, w_img = mask.shape[:2]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    blobs = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < np.pi * min_radius ** 2 * 0.5:
            continue
        (_, _), r = cv2.minEnclosingCircle(c)
        if r < min_radius:
            continue
        blobs.append(measure(c, area, w_img, h_img))
    return blobs


def group_pieces(blobs, mask_shape):
    """v3: fingers across a ball split it into pieces. Group pieces that
    touch each other's enclosing circles into one candidate."""
    h_img, w_img = mask_shape[:2]
    n = len(blobs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            a, b = blobs[i], blobs[j]
            if max(a["r"], b["r"]) > 150:
                continue
            if ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 < (a["r"] + b["r"]) * 1.05 + 4:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        if 2 <= len(members) <= 5:
            pts = np.vstack([blobs[i]["points"] for i in members])
            g = measure(pts, sum(blobs[i]["area"] for i in members), w_img, h_img)
            g["members"] = members
            out.append(g)
    return out


# ============================================================
# SHAPE CHECKS
# ============================================================

def shape_check_v1(b):
    """v1: blob must fill at least 40 % of its enclosing circle."""
    fill = b["area"] / (np.pi * b["r"] ** 2)
    return (True, "") if fill >= 0.4 else (False, "not round")


def shape_check(b, strictness, lenient=False):
    """v2/v3: is this blob ball-shaped? Returns (ok, reason).

    lenient=True is used for blobs close to where the tracked ball is
    expected, so fast, blurred or partly hidden balls are kept.
    """
    st = strictness
    sol_min = 0.55 + 0.40 * st          # st=0.7 -> 0.83
    rect_max = 1.00 - 0.10 * st         # st=0.7 -> 0.93
    rect_min = 0.45 + 0.25 * st         # st=0.7 -> 0.63
    aspect_max = 5.0 - 3.5 * st         # st=0.7 -> 2.55
    if lenient:
        # Corner check stays strict (blurred balls are <= 0.92 anyway),
        # everything else is relaxed for blurred / partly hidden balls.
        sol_min -= 0.12
        rect_min -= 0.10
        aspect_max *= 1.7

    if b["solidity"] < sol_min:
        return False, "ragged"
    if b["rect_fill"] > rect_max:
        return False, "corners"
    if b["border"]:
        return True, ""                  # half a ball at the edge: no roundness check
    if b["rect_fill"] < rect_min:
        return False, "not round"
    if b["aspect"] > aspect_max:
        return False, "stretched"
    return True, ""


# ---- v3: circle fit on the visible edge (hand occlusion) -------------------

_rng = np.random.default_rng(0)


def _circle_from_3(p):
    (x1, y1), (x2, y2), (x3, y3) = p
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-6:
        return None
    s1, s2, s3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    ux = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    uy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return ux, uy, np.hypot(x1 - ux, y1 - uy)


def _fit_circle_ls(pts):
    x, y = pts[:, 0], pts[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    (cx, cy, c), *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    return cx, cy, float(np.sqrt(max(c + cx * cx + cy * cy, 1e-6)))


def fit_visible_circle(points, r_max, iters=60):
    """RANSAC circle fit on the outline. Points on the hand's edge are
    outliers; the round part of the outline decides the circle.
    Returns (cx, cy, r, coverage_degrees, inlier_fraction, outside_fraction)."""
    pts = points.reshape(-1, 2).astype(np.float64)
    if len(pts) > 400:
        pts = pts[np.linspace(0, len(pts) - 1, 400).astype(int)]
    n = len(pts)
    if n < 10:
        return None
    best_k, best_inl = 0, None
    for _ in range(iters):
        c = _circle_from_3(pts[_rng.choice(n, 3, replace=False)])
        if c is None or c[2] < 3 or c[2] > r_max:
            continue
        d = np.abs(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) - c[2])
        inl = d < max(1.5, 0.06 * c[2])
        k = int(inl.sum())
        if k > best_k:
            best_k, best_inl = k, inl
    if best_inl is None or best_k < 8:
        return None
    cx, cy, r = _fit_circle_ls(pts[best_inl])
    if r > r_max:
        return None
    dist = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    inl = np.abs(dist - r) < max(1.5, 0.06 * r)
    ang = np.arctan2(pts[inl, 1] - cy, pts[inl, 0] - cx)
    coverage = len(np.unique(((ang + np.pi) / (2 * np.pi) * 36).astype(int) % 36)) * 10
    outside = float((dist > r * 1.15 + 2).mean())
    return cx, cy, r, coverage, float(inl.mean()), outside


def circle_fill(mask, cx, cy, r):
    """Fraction of the fitted circle that is ball-colored."""
    h_img, w_img = mask.shape[:2]
    x0, x1 = int(max(0, cx - r)), int(min(w_img, cx + r + 1))
    y0, y1 = int(max(0, cy - r)), int(min(h_img, cy + r + 1))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    if inside.sum() == 0:
        return 0.0
    return float((mask[y0:y1, x0:x1][inside] > 0).mean())


def occlusion_check(b, mask, strictness, lenient, ball_width):
    """v3: accept a partly hidden ball. Sets b's position/radius to the
    fitted circle (the TRUE center, not the center of the visible part)."""
    if b["rect_fill"] > 1.00 - 0.10 * strictness:
        return False, "corners"
    fit = fit_visible_circle(b["points"], r_max=b["r"] * 1.3 + 2)
    if fit is None:
        return False, b["reason"] or "no circle"
    cx, cy, r, coverage, inliers, outside = fit
    st = strictness
    cov_min = 150 + 40 * st             # degrees of visible round edge; st=0.7 -> 178
    inl_min = 0.45 + 0.15 * st          # share of the outline on the circle
    fill_min = 0.35 + 0.20 * st         # share of the circle that is ball-colored
    if lenient:
        cov_min, inl_min, fill_min = cov_min - 50, inl_min - 0.10, fill_min - 0.12
    if r < b["r"] * 0.6:
        return False, "no circle"
    if lenient and ball_width > 0 and not (ball_width / 1.6 <= 2 * r <= ball_width * 1.6):
        return False, "size"
    if coverage < cov_min or inliers < inl_min or outside > 0.2:
        return False, "no circle"
    if circle_fill(mask, cx, cy, r) < fill_min:
        return False, "no circle"
    b.update(x=cx, y=cy, r=r, width=2 * r, kind="partial")
    return True, ""


# ============================================================
# VALUE DISPLAY
# ============================================================

def draw_values(frame, pos, vx, vy, snd):
    """Panel top left: position, velocity and the sound values as numbers."""
    x0, y0, w, h = 15, 50, 300, 232
    roi = frame[y0:y0 + h, x0:x0 + w]
    frame[y0:y0 + h, x0:x0 + w] = (roi * 0.35).astype(np.uint8)   # darkened background

    def row(i, label, value, color=(255, 255, 255)):
        yy = y0 + 26 + i * 24
        cv2.putText(frame, label, (x0 + 10, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (170, 170, 170), 1, cv2.LINE_AA)
        cv2.putText(frame, value, (x0 + 120, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)

    if pos is None:
        row(0, "x", "-")
        row(1, "y", "-")
    else:
        row(0, "x", f"{pos[0]:6.0f} px")
        row(1, "y", f"{pos[1]:6.0f} px")
    row(2, "vx", f"{vx:+6.0f} px/s")
    row(3, "vy", f"{vy:+6.0f} px/s")
    row(4, "velocity", f"{snd['speed']:6.0f} px/s")
    arrow = {"G": "G  (-> right)", "A": "A  (<- left)"}.get(snd["note"], "-")
    row(5, "note", arrow, (0, 255, 255))
    row(6, "volume", f"{snd['volume'] * 100:5.0f} %")
    row(7, "filter", f"{snd['cutoff']:6.0f} Hz")
    # volume bar
    bw = int((w - 20) * snd["volume"])
    cv2.rectangle(frame, (x0 + 10, y0 + h - 14), (x0 + w - 10, y0 + h - 8), (60, 60, 60), -1)
    cv2.rectangle(frame, (x0 + 10, y0 + h - 14), (x0 + 10 + bw, y0 + h - 8), (0, 255, 255), -1)


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
    if is_camera:
        # 1280x720 instead of full HD: most webcams deliver more frames per
        # second at this size -> less motion blur, fast balls seen earlier.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        cap.set(cv2.CAP_PROP_FPS, 60)   # ask for 60 fps; camera uses its max if lower

    file_fps = cap.get(cv2.CAP_PROP_FPS) if not is_camera else 0
    file_dt = 1.0 / file_fps if file_fps and file_fps > 0 else 1 / 30

    settings = load_settings()
    if args.strictness is not None:
        settings["strictness"] = int(round(args.strictness * 100))
    version = args.version
    show_mask = False
    clicked = []   # mouse clicks from the window callback

    if not args.no_show:
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.createTrackbar("Version", WINDOW, version, 3, lambda v: None)
        try:
            cv2.setTrackbarMin("Version", WINDOW, 1)
        except cv2.error:
            pass   # older OpenCV builds: 0 is treated as 1
        cv2.setMouseCallback(WINDOW, lambda ev, x, y, fl, prm:
                             clicked.append((x, y)) if ev == cv2.EVENT_LBUTTONDOWN else None)
        print("Keys: 1/2/3 = version, click ball = pick color, m = mask, s = save, q = quit")

    writer = None
    if args.save:
        out_fps = file_fps if file_fps and file_fps > 0 else 30
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), out_fps,
                                 (args.width, args.height))

    # ---- Sound -------------------------------------------------------------------
    sound = BallSound(args.width, args.height, max_speed=args.max_speed)
    audio_chunks, audio_pos = [], 0.0
    if args.audio_out:
        print(f"Sound -> {args.audio_out} (in sync with the frames)")
    elif not args.no_audio:
        try:
            dev = int(args.audio_device) if args.audio_device and args.audio_device.isdigit() else args.audio_device
            sound.synth.start(dev)
            print("Sound on: ball right -> G, left -> A, speed -> volume, y -> filter")
        except ImportError:
            print("No sound: sounddevice is missing. Install with: pip install sounddevice")
        except Exception as e:
            print(f"No sound ({e}). Check the output device (--audio-device) or use --no-audio.")

    tracker = BallKalman()

    def reset_track():
        nonlocal missed, track_age, radius, ball_width, holding, hidden_time
        tracker.initialized = False
        trail.clear()
        missed = track_age = 0
        radius = ball_width = hidden_time = 0.0
        holding = False

    missed = 0
    track_age = 0          # frames since the track started
    radius = 0.0
    ball_width = 0.0       # smoothed diameter of the tracked ball
    holding = False        # v3: ball disappeared while slow -> probably in a hand
    hidden_time = 0.0
    trail = []
    frame_idx = 0
    counts = {"full": 0, "partial": 0, "predicted": 0, "hidden": 0}
    cam_fails = 0
    last_t = time.perf_counter()
    fps_smooth = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            if is_camera and cam_fails < 150:      # camera warm-up
                cam_fails += 1
                time.sleep(0.02)
                continue
            if is_camera and frame_idx == 0:
                print("No image from the camera. Run camera_check.py to find the right --source.")
            break
        cam_fails = 0
        frame = cv2.resize(frame, (args.width, args.height))
        if args.mirror:
            frame = cv2.flip(frame, 1)

        now = time.perf_counter()
        loop_dt = now - last_t
        last_t = now
        dt = min(max(loop_dt if is_camera else file_dt, 1e-3), 0.2)

        # ---- 0. Version switch (slider or keys) ----------------------------
        if not args.no_show:
            v = max(1, cv2.getTrackbarPos("Version", WINDOW))
            if v != version:
                version = v
                reset_track()
                print(f"Switched to {VERSION_NAMES[version]}")

        # ---- 1. Color mask -------------------------------------------------
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        if clicked:
            cx, cy = clicked.pop()
            clicked.clear()
            settings = {**settings_from_click(hsv, cx, cy), "strictness": settings["strictness"]}
            print(f"Picked color at ({cx}, {cy}): {settings}")
            if show_mask:
                write_sliders(settings)
        elif show_mask:
            read_sliders(settings)

        mask = make_mask(hsv, settings, version)
        blobs = find_blobs(mask, args.min_radius)
        strictness = settings["strictness"] / 100.0

        # ---- 2. Predict -----------------------------------------------------
        if holding:
            tracker.damp_velocity(0.5)   # held ball: assume it stays where it vanished
        pred = tracker.predict(dt) if tracker.initialized else None
        gate = 0.0
        if pred is not None:
            vx, vy = tracker.velocity
            # Search radius around the prediction. Larger while the track is
            # new (velocity not known yet) and while the ball is hidden.
            gate = 100 + (vx * vx + vy * vy) ** 0.5 * dt * 2 + missed * 25
            if version >= 2 and track_age < 4:
                gate += 150
            if holding:
                gate = min(gate, 250)

        def is_near(b):
            return pred is not None and ((b["x"] - pred[0]) ** 2 + (b["y"] - pred[1]) ** 2) ** 0.5 <= gate

        # ---- 3. Shape checks ------------------------------------------------
        accepted, rejected = [], []
        for b in blobs:
            near = is_near(b)
            if version == 1:
                ok, reason = shape_check_v1(b)
            else:
                # near the prediction, but a different size than our ball -> something else
                if near and ball_width > 0 and not b["border"] and \
                        not (ball_width / 1.8 <= b["width"] <= ball_width * 1.8):
                    near = False
                ok, reason = shape_check(b, strictness, lenient=near)
                b["reason"] = reason
                if not ok and version == 3 and reason != "corners":
                    ok, reason = occlusion_check(b, mask, strictness, is_near(b), ball_width)
                    near = ok and is_near(b)
            b["near"], b["reason"] = near, reason
            (accepted if ok else rejected).append(b)

        if version == 3:
            # Ball split into pieces by fingers: try the pieces as one ball
            for g in group_pieces(blobs, mask.shape):
                if any(blobs[i]["kind"] == "full" and any(blobs[i] is a for a in accepted)
                       for i in g["members"]):
                    continue
                ok, _ = occlusion_check(g, mask, strictness, is_near(g), ball_width)
                if ok:
                    g["near"] = is_near(g)
                    members = [blobs[i] for i in g["members"]]
                    accepted = [b for b in accepted if not any(b is m for m in members)]
                    rejected = [b for b in rejected if not any(b is m for m in members)]
                    accepted.append(g)

        # ---- 4. Choose the blob that is our ball ---------------------------
        measurement = None
        if accepted:
            near_ones = [b for b in accepted if b["near"]]
            if near_ones:
                measurement = min(near_ones, key=lambda b: (b["x"] - pred[0]) ** 2 + (b["y"] - pred[1]) ** 2)
            elif not holding or version < 3:
                biggest = max(accepted, key=lambda b: b["area"])
                if pred is None or biggest["area"] > 4 * max(np.pi * radius ** 2, 1):
                    measurement = biggest      # new ball, or a much bigger one elsewhere
                    tracker.initialized = False
            else:
                # Holding: only jump elsewhere for a clearly visible ball
                full = [b for b in accepted if b["kind"] == "full" and not b["border"]]
                if full:
                    measurement = max(full, key=lambda b: b["area"])
                    tracker.initialized = False

        # ---- 5. Update ------------------------------------------------------
        state, pos = None, None   # full / partial / predicted / hidden
        if measurement is not None:
            mx, my, mr = measurement["x"], measurement["y"], measurement["r"]
            if measurement["border"] and radius > 0 and measurement["kind"] == "full":
                mr = max(mr, radius)               # don't shrink while half outside
            radius = mr if radius == 0 or not tracker.initialized else 0.6 * radius + 0.4 * mr
            if not measurement["border"]:
                mw = measurement["width"]
                ball_width = mw if ball_width == 0 or not tracker.initialized else 0.7 * ball_width + 0.3 * mw
            if not tracker.initialized:
                tracker.init(mx, my)
                trail.clear()
                track_age = 0
                pos = (mx, my)
            else:
                pos = tracker.correct(mx, my)
            track_age += 1
            missed, holding, hidden_time = 0, False, 0.0
            state = measurement["kind"]
        elif tracker.initialized:
            if missed == 0 and version == 3:
                vx, vy = tracker.velocity
                holding = (vx * vx + vy * vy) ** 0.5 < 300   # slow when it vanished -> in a hand
            missed += 1
            hidden_time += dt
            m_out = max(radius, 10)
            off_screen = not (-m_out <= pred[0] <= args.width + m_out and -m_out <= pred[1] <= args.height + m_out)
            lost = hidden_time > args.hold_seconds if holding else missed > args.max_missed
            if version == 1:
                off_screen = False   # v1 had no off-screen check
            if lost or off_screen:
                reset_track()
            else:
                pos = pred
                state = "hidden" if holding else "predicted"

        vx, vy = tracker.velocity if pos is not None else (0.0, 0.0)
        if pos is not None:
            counts[state] += 1
            on_ball(frame_idx, pos[0], pos[1], radius, vx, vy, state in ("full", "partial"))
            trail.append((pos[0], pos[1], state))
            trail = trail[-40:]

        # ---- Sound: direction -> note, speed -> volume, y -> filter ---------------
        snd = sound.update(pos, vx, vy)
        if args.audio_out:
            audio_pos += sound.synth.sr * dt
            n = int(audio_pos)
            audio_pos -= n
            audio_chunks.append(sound.synth.render(n))

        fps_now = 1.0 / loop_dt if loop_dt > 0 else 0
        fps_smooth = fps_now if fps_smooth == 0 else 0.9 * fps_smooth + 0.1 * fps_now

        # ---- 6. Draw ----------------------------------------------------------
        colors = {"full": COL_DETECTED, "partial": COL_PARTIAL, "predicted": COL_PREDICTED, "hidden": COL_HIDDEN}
        if not args.no_show or writer:
            if show_mask:
                # Debug view: why blobs were rejected
                for b in rejected:
                    cv2.circle(frame, (int(b["x"]), int(b["y"])), int(b["r"]), (150, 150, 150), 1)
                    cv2.putText(frame, b["reason"], (int(b["x"] - b["r"]), int(b["y"] - b["r"] - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
            for i in range(1, len(trail)):
                (x0, y0, s0), (x1, y1, _) = trail[i - 1], trail[i]
                cv2.line(frame, (int(x0), int(y0)), (int(x1), int(y1)), colors[s0], 2)
            if pos is not None:
                cv2.circle(frame, (int(pos[0]), int(pos[1])), int(max(radius, 6)) + 4, colors[state], 2)
                cv2.circle(frame, (int(pos[0]), int(pos[1])), 3, colors[state], -1)
            labels = {"full": "detected", "partial": "detected (partly hidden)",
                      "predicted": "predicted", "hidden": "hidden (in hand?)"}
            status = labels.get(state, "searching")
            cv2.putText(frame, f"{VERSION_NAMES[version]} | {fps_smooth:5.1f} FPS | {status}", (15, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            draw_values(frame, pos, vx, vy, snd)
            cv2.putText(frame, "1/2/3 = version | click ball = pick color | m = mask | s = save | q = quit",
                        (15, args.height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        if writer:
            writer.write(frame)

        if not args.no_show:
            cv2.imshow(WINDOW, frame)
            if show_mask:
                cv2.imshow("Mask", cv2.resize(mask, (640, 360)))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key in (ord("1"), ord("2"), ord("3")):
                cv2.setTrackbarPos("Version", WINDOW, key - ord("0"))   # picked up next frame
            elif key == ord("m"):
                show_mask = not show_mask
                if show_mask:
                    create_mask_window(settings)
                else:
                    cv2.destroyWindow("Mask")
            elif key == ord("s"):
                save_settings(settings)
            elif key == ord("r"):
                settings = dict(DEFAULT_GREEN)
                if show_mask:
                    write_sliders(settings)
                print("Reset to default green")
        elif frame_idx % 50 == 0:
            p = f"({pos[0]:.0f}, {pos[1]:.0f}) r={radius:.0f}" if pos else "-"
            print(f"frame {frame_idx:5d} | {fps_smooth:6.1f} FPS | {state or '-':9s} {p} | "
                  f"vx={vx:6.0f} speed={snd['speed']:5.0f} note={snd['note']} "
                  f"vol={snd['volume']:.2f} filter={snd['cutoff']:5.0f}Hz")

        frame_idx += 1

    cap.release()
    sound.synth.stop()
    if args.audio_out and audio_chunks:
        from scipy.io import wavfile
        wavfile.write(args.audio_out, sound.synth.sr, np.concatenate(audio_chunks))
        print(f"Wrote {args.audio_out}")
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    lost = frame_idx - sum(counts.values())
    print(f"Done ({VERSION_NAMES[version]}). {frame_idx} frames | visible {counts['full']}, "
          f"partly hidden {counts['partial']}, predicted {counts['predicted']}, "
          f"hidden {counts['hidden']}, no ball {lost}")


if __name__ == "__main__":
    main()

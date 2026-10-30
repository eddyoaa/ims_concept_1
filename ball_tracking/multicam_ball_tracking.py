# ============================================================
# BALL TRACKING WITH TWO CAMERAS  (depth + occlusion)
# ============================================================
# Same color tracking as color_ball_tracking.py, but with a second camera
# looking at the scene from the SIDE, roughly at a right angle:
#
#            side camera
#                 |
#                 v
#        +-----------------+
#        |   scene / balls |
#        +-----------------+
#                 ^
#                 |
#           front camera
#
#   front camera -> x (left/right) and y (height)
#   side camera  -> z (depth: near/far from the front camera) and y
#
# Depth: z comes from the side camera.
# Occlusion: if one camera loses a ball (hand in front of it), the other
# one keeps the ball: its height keeps moving, the missing coordinate is
# held at the last known value.
# Height (y) of the two cameras is matched automatically: whenever both
# cameras see a ball, the side camera's y is fitted onto the front camera's
# y (no calibration board needed). Move the balls up and down a bit at the
# start; the panel shows "y sync: ok" when it's done.
#
# This is the quick, calibration-free setup. It ignores perspective, so the
# values are "rough 3D" (good for sound control, not for measuring).
#
# Usage:
#   python multicam_ball_tracking.py --source 0 --side 1
#   python multicam_ball_tracking.py --source front.mp4 --side side.mp4
#
# Keys / mouse (one window, front image left, side image right):
#   1 / 2 / 3           -> detection version (both cameras)
#   LEFT CLICK on ball  -> color of the active ball, in the camera you clicked
#   RIGHT CLICK on ball -> color of ball 2, in the camera you clicked
#   b / TAB             -> switch the active ball
#   c                   -> switch the active camera (for the mask window and 'r')
#   m                   -> mask window + sliders (active camera, active ball)
#   s                   -> save colors of both cameras
#   r                   -> reset active ball of the active camera to its default color
#   q / ESC             -> quit
#
# Each camera has its own color settings (light and white balance differ):
#   front -> color_settings.json (same file as color_ball_tracking.py)
#   side  -> color_settings_side.json
# ============================================================

import threading
import time
from collections import deque

import cv2
import numpy as np

from ball_sound import NOTE_PAIRS, BallSound, Mixer
from color_ball_tracking import (DEFAULT_BALLS, SETTINGS_FILE, VERSION_NAMES, BallTrack, build_parser,
                                 create_mask_window, load_settings, read_sliders, save_settings,
                                 settings_from_click, warn_overlap, write_sliders)

SIDE_SETTINGS_FILE = "color_settings_side.json"
WINDOW = "Multicam Ball Tracking"
CAM_NAMES = ["FRONT", "SIDE"]
PANEL_H = 270


def parse_args():
    p = build_parser("Ball tracking with two cameras (front + side) for depth and occlusion")
    p.add_argument("--side", required=True, help="Side camera index or video file")
    p.add_argument("--side-flip", action="store_true",
                   help="Reverse the depth direction (use it if z grows when the ball comes closer "
                        "to the front camera)")
    p.add_argument("--side-mirror", action="store_true", help="Mirror the side camera image")
    return p.parse_args()


# ============================================================
# HOOK FOR YOUR OWN CODE
# ============================================================

def on_ball_3d(ball, frame_idx, x, y, z, vx, vy, vz, seen):
    """Called once per frame and ball while that ball is tracked by at least one camera.

    ball      : 0 = ball 1, 1 = ball 2
    x, y, z   : 0..1. x = left->right (front camera), y = top->bottom,
                z = near->far from the front camera (side camera).
                x or z is None until the camera that measures it has seen the ball once.
    vx, vy, vz: velocity in image widths per second
    seen      : "front+side", "front", "side" or "predicted"
    """
    pass


# ============================================================
# CAMERA INPUT
# ============================================================

class Camera:
    """A camera in its own thread (always the newest frame), or a video file (frame by frame).

    The thread matters with two cameras: each one runs at its own pace, and
    every frame gets the time it arrived, so positions can be lined up in time.
    """

    def __init__(self, name, source, args, mirror=False):
        self.name = name
        self.src = int(source) if str(source).isdigit() else source
        self.is_camera = isinstance(self.src, int)
        self.w, self.h, self.mirror = args.width, args.height, mirror
        self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            raise SystemExit(f"Could not open {name} source: {source}")
        self.file_dt = 1 / 30
        if self.is_camera:
            # MJPG = compressed over USB, so two cameras fit on one USB bus
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            self.cap.set(cv2.CAP_PROP_FPS, 60)
        else:
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.file_dt = 1.0 / fps if fps and fps > 0 else 1 / 30
        self.idx = 0
        self.last_t = None
        self.fps = 0.0
        self.failed = False
        self._cond = threading.Condition()
        self._frame, self._t, self._seq, self._seen = None, 0.0, 0, 0
        self._running = True
        self._thread = None
        if self.is_camera:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self):
        fails = 0
        while self._running:
            ok, f = self.cap.read()
            t = time.perf_counter()
            if not ok or f is None:
                fails += 1
                if fails > 150:                      # ~3 s without a frame
                    with self._cond:
                        self.failed = True
                        self._cond.notify_all()
                    return
                time.sleep(0.02)
                continue
            fails = 0
            with self._cond:
                self._frame, self._t = f, t
                self._seq += 1
                self._cond.notify_all()

    def read(self, wait=True, timeout=3.0):
        """Next frame as (frame, t, dt), or None.
        Camera: newest frame; with wait=False None if there is nothing new yet."""
        if self.is_camera:
            with self._cond:
                if wait:
                    self._cond.wait_for(lambda: self._seq != self._seen or self.failed, timeout)
                if self._seq == self._seen:
                    return None
                f, t = self._frame, self._t
                self._seen = self._seq
        else:
            ok, f = self.cap.read()
            if not ok:
                return None
            t = self.idx * self.file_dt
        self.idx += 1
        f = cv2.resize(f, (self.w, self.h))
        if self.mirror:
            f = cv2.flip(f, 1)
        dt = self.file_dt if not self.is_camera or self.last_t is None else t - self.last_t
        dt = min(max(dt, 1e-3), 0.2)
        self.last_t = t
        self.fps = 1 / dt if self.fps == 0 else 0.9 * self.fps + 0.1 / dt
        return f, t, dt

    def release(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.cap.release()


# ============================================================
# FUSION: two 2D tracks -> one 3D position
# ============================================================

class YMapper:
    """Maps the side camera's height onto the front camera's height.

    Learns a straight line y_front = a * y_side + b from frames where both
    cameras see the same ball. Needs some up/down movement to be reliable.
    """
    MIN_PAIRS = 40

    def __init__(self):
        self.pairs = deque(maxlen=900)
        self.a, self.b = 1.0, 0.0
        self.ready = False
        self._n = 0

    def add(self, y_side, y_front):
        self.pairs.append((y_side, y_front))
        self._n += 1
        if len(self.pairs) >= self.MIN_PAIRS and self._n % 10 == 0:
            p = np.array(self.pairs)
            if p[:, 0].std() < 0.05:
                return                      # not enough up/down movement yet
            a, b = np.polyfit(p[:, 0], p[:, 1], 1)
            if 0.3 < a < 3.0:
                self.a, self.b, self.ready = float(a), float(b), True

    def map(self, y):
        return self.a * y + self.b

    @property
    def status(self):
        if self.ready:
            return f"y sync: ok (a={self.a:.2f} b={self.b:+.2f})"
        return f"y sync: learning {len(self.pairs)}/{self.MIN_PAIRS} - move balls up/down"


def track_at(track, t_frame, t, w, h):
    """Position of a camera track at time t (normalized 0..1), or None.
    The two cameras don't take their pictures at the same moment, so each
    position is moved forward along its velocity to the common time t."""
    if track is None or track.pos is None:
        return None
    d = min(max(t - t_frame, 0.0), 0.1)
    return {"u": (track.pos[0] + track.vx * d) / w, "y": (track.pos[1] + track.vy * d) / h,
            "vu": track.vx / w, "vy": track.vy / h, "seen": track.state in ("full", "partial")}


class FusedBall:
    """One ball in 3D: x from the front camera, z from the side camera, y from both."""

    def __init__(self, index):
        self.index = index
        self.name = f"Ball {index + 1}"
        self.counts = {}
        self.reset()

    def reset(self):
        self.x = self.y = self.z = None
        self.vx = self.vy = self.vz = 0.0
        self.seen = None

    @property
    def tracked(self):
        return self.y is not None

    def update(self, fa, fb, ymap, side_flip):
        """fa / fb: front / side track at the common time (from track_at)."""
        if fa is None and fb is None:
            self.reset()
            self.counts["none"] = self.counts.get("none", 0) + 1
            return
        if fa and fb and fa["seen"] and fb["seen"]:
            ymap.add(fb["y"], fa["y"])

        # x only from the front camera; held while the front camera has lost the ball
        if fa:
            self.x, self.vx = fa["u"], fa["vu"]
        else:
            self.vx = 0.0
        # z only from the side camera; held while the side camera has lost the ball
        if fb:
            z, vz = fb["u"], fb["vu"]
            if side_flip:
                z, vz = 1.0 - z, -vz
            self.z, self.vz = z, vz
        else:
            self.vz = 0.0

        # y from both: a camera that sees the ball counts more than one that only predicts it
        ys = []
        if fa:
            ys.append((fa["y"], fa["vy"], 1.0 if fa["seen"] else 0.2))
        if fb and (ymap.ready or fa is None):
            if ymap.ready:
                ys.append((ymap.map(fb["y"]), ymap.a * fb["vy"], 1.0 if fb["seen"] else 0.2))
            else:
                ys.append((fb["y"], fb["vy"], 1.0))
        if any(w == 1.0 for _, _, w in ys):
            ys = [c for c in ys if c[2] == 1.0]   # a camera that sees the ball beats a guess
        wsum = sum(w for _, _, w in ys)
        self.y = sum(y * w for y, _, w in ys) / wsum
        self.vy = sum(v * w for _, v, w in ys) / wsum

        names = [n for n, f in (("front", fa), ("side", fb)) if f and f["seen"]]
        self.seen = "+".join(names) or "predicted"
        self.counts[self.seen] = self.counts.get(self.seen, 0) + 1


# ============================================================
# DISPLAY
# ============================================================

def draw_camera_view(frame, cam, tracks, show_rejected, active_cam, scale):
    """Camera image with markers, downscaled for the combined window."""
    for t in tracks:
        t.draw(frame, show_rejected)
    small = cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))
    axes = "x / y" if cam.name == "FRONT" else "z / y"
    cv2.putText(small, f"{cam.name} ({axes}) {cam.fps:4.0f} FPS", (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (255, 255, 255), 2, cv2.LINE_AA)
    for i, t in enumerate(tracks):
        cv2.putText(small, f"{t.index + 1}: {t.status}", (10, 48 + i * 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, t.color, 1, cv2.LINE_AA)
    if active_cam:
        cv2.rectangle(small, (0, 0), (small.shape[1] - 1, small.shape[0] - 1), (255, 255, 255), 1)
    return small


def fmt(v, unit=""):
    return "-" if v is None else f"{v:5.2f}{unit}"


def draw_panel(canvas, y0, fused, snds, colors, ymap, version, active):
    w = canvas.shape[1]
    canvas[y0:] = (30, 30, 30)

    def text(s, x, y, color=(255, 255, 255), size=0.55, thick=1):
        cv2.putText(canvas, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, size, color, thick, cv2.LINE_AA)

    # values per ball
    for fb, snd, col in zip(fused, snds, colors):
        x0 = 15 + fb.index * 330
        text(fb.name + ("  (active)" if len(fused) > 1 and fb.index == active else ""),
             x0, y0 + 24, col, 0.6, 2)
        speed_px = snd["speed"]
        arrow = {"right": " (-> right)", "left": " (<- left)"}.get(snd["direction"], "")
        rows = [("seen by", fb.seen or "-"), ("x", fmt(fb.x)), ("y", fmt(fb.y)), ("z (depth)", fmt(fb.z)),
                ("velocity", f"{speed_px:5.0f} px/s"), ("note", snd["note"] + arrow),
                ("volume", f"{snd['volume'] * 100:4.0f} %"), ("filter", f"{snd['cutoff']:5.0f} Hz")]
        for i, (k, v) in enumerate(rows):
            text(k, x0, y0 + 50 + i * 22, (170, 170, 170))
            text(v, x0 + 105, y0 + 50 + i * 22, (0, 255, 255) if k == "note" else (255, 255, 255))

    # top view: x left->right, z from the front camera (bottom) into the room (top)
    size = PANEL_H - 50
    mx0, my0 = w - size - 20, y0 + 30
    cv2.rectangle(canvas, (mx0, my0), (mx0 + size, my0 + size), (90, 90, 90), 1)
    text("top view (x / z)", mx0, my0 - 8, (170, 170, 170), 0.5)
    text("front cam", mx0 + size // 2 - 38, my0 + size - 6, (120, 120, 120), 0.45)
    for fb, col in zip(fused, colors):
        if fb.tracked and fb.x is not None and fb.z is not None:
            px = int(mx0 + np.clip(fb.x, 0, 1) * size)
            py = int(my0 + size - np.clip(fb.z, 0, 1) * size)
            cv2.circle(canvas, (px, py), 8, col, -1)
            text(str(fb.index + 1), px + 10, py + 5, col, 0.5)

    text(ymap.status, 680, y0 + 24, (0, 255, 0) if ymap.ready else (0, 200, 255), 0.5)
    text(VERSION_NAMES[version], 680, y0 + 46, (170, 170, 170), 0.5)
    text("click = color | b = ball | c = camera | m = mask | s = save | q = quit",
         15, canvas.shape[0] - 10, (200, 200, 200), 0.5)


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    args = parse_args()
    cams = [Camera("FRONT", args.source, args, mirror=args.mirror),
            Camera("SIDE", args.side, args, mirror=args.side_mirror)]
    files = [SETTINGS_FILE, SIDE_SETTINGS_FILE]
    cam_settings = [load_settings(f) for f in files]
    if args.strictness is not None:
        for sl in cam_settings:
            for s in sl:
                s["strictness"] = int(round(args.strictness * 100))
    cam_tracks = [[BallTrack(i, cam_settings[c][i], args) for i in range(args.balls)] for c in range(2)]
    for c in range(2):
        warn_overlap(cam_tracks[c])
    fused = [FusedBall(i) for i in range(args.balls)]
    ymap = YMapper()

    version = args.version
    show_mask = False
    active, active_cam = 0, 0
    clicked = []     # (camera, x, y, ball or None = active ball)

    scale = 0.5
    view_w, view_h = int(args.width * scale), int(args.height * scale)
    canvas_size = (view_w * 2, view_h + PANEL_H)   # (w, h)

    def on_mouse(ev, x, y, flags, param):
        if y >= view_h or ev not in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
            return
        if ev == cv2.EVENT_RBUTTONDOWN and args.balls < 2:
            return
        c = min(x // view_w, 1)
        ball = None if ev == cv2.EVENT_LBUTTONDOWN else 1
        clicked.append((c, int((x - c * view_w) / scale), int(y / scale), ball))

    if not args.no_show:
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.createTrackbar("Version", WINDOW, version, 3, lambda v: None)
        try:
            cv2.setTrackbarMin("Version", WINDOW, 1)
        except cv2.error:
            pass
        cv2.setMouseCallback(WINDOW, on_mouse)
        print("Click each ball in BOTH camera images to pick its color (left = active ball, "
              "right = ball 2). Then move the balls up and down so the heights get matched.")

    writer = None
    if args.save:
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"),
                                 1 / cams[0].file_dt if not cams[0].is_camera else 30, canvas_size)

    # ---- Sound: one voice per ball --------------------------------------------------
    sounds = [BallSound(args.width, args.height, max_speed=args.max_speed, notes=NOTE_PAIRS[i],
                        gain=0.35 if args.balls == 1 else 0.28) for i in range(args.balls)]
    mixer = Mixer([s.synth for s in sounds])
    audio_chunks, audio_pos = [], 0.0
    if args.audio_out:
        print(f"Sound -> {args.audio_out}")
    elif not args.no_audio:
        try:
            dev = int(args.audio_device) if args.audio_device and args.audio_device.isdigit() else args.audio_device
            mixer.start(dev)
        except ImportError:
            print("No sound: sounddevice is missing. Install with: pip install sounddevice")
        except Exception as e:
            print(f"No sound ({e}). Check the output device (--audio-device) or use --no-audio.")

    views = [np.zeros((view_h, view_w, 3), np.uint8) for _ in range(2)]
    cam_t = [0.0, 0.0]
    frame_idx = 0

    while True:
        # Front camera sets the pace; the side camera delivers whatever it has new.
        reads = [cams[0].read(wait=True), cams[1].read(wait=not cams[1].is_camera)]
        if reads[0] is None:
            if cams[0].is_camera and frame_idx == 0:
                print("No image from the front camera. Run camera_check.py to find the right --source.")
            break
        if cams[1].failed and frame_idx % 100 == 0:
            print("Side camera delivers no images (check --side).")
        front_dt = reads[0][2]

        if not args.no_show:
            v = max(1, cv2.getTrackbarPos("Version", WINDOW))
            if v != version:
                version = v
                for tl in cam_tracks:
                    for t in tl:
                        t.reset()
                print(f"Switched to {VERSION_NAMES[version]}")

        for c, r in enumerate(reads):
            if r is None:
                continue          # no new frame from this camera: keep its last state
            frame, t_frame, dt = r
            hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)

            mine = [k for k in clicked if k[0] == c]
            if mine:
                _, cx, cy, ball = mine[-1]
                clicked[:] = [k for k in clicked if k[0] != c]
                t = cam_tracks[c][active if ball is None else ball]
                t.settings.update(settings_from_click(hsv, cx, cy))
                print(f"{CAM_NAMES[c]} {t.name}: picked color at ({cx}, {cy}): {t.settings}")
                warn_overlap(cam_tracks[c])
                if show_mask and c == active_cam and t.index == active:
                    write_sliders(t.settings)
            elif show_mask and c == active_cam:
                read_sliders(cam_tracks[c][active].settings)

            for t in cam_tracks[c]:
                t.step(hsv, dt, version)
            cam_t[c] = t_frame
            if not args.no_show or writer:
                views[c] = draw_camera_view(frame, cams[c], cam_tracks[c],
                                            show_mask and c == active_cam, c == active_cam, scale)

        # ---- Fusion: both cameras at the same moment -> x, y, z ----------------
        t_now = max(cam_t)
        snds = []
        for i, fb in enumerate(fused):
            fa = track_at(cam_tracks[0][i], cam_t[0], t_now, args.width, args.height)
            fs = track_at(cam_tracks[1][i], cam_t[1], t_now, args.width, args.height)
            fb.update(fa, fs, ymap, args.side_flip)
            if fb.tracked:
                on_ball_3d(i, frame_idx, fb.x, fb.y, fb.z, fb.vx, fb.vy, fb.vz, fb.seen)
                pos = ((fb.x if fb.x is not None else 0.5) * args.width, fb.y * args.height)
                snds.append(sounds[i].update(pos, fb.vx * args.width, fb.vy * args.height,
                                             fb.vz * args.width))
            else:
                snds.append(sounds[i].update(None, 0.0, 0.0))

        if args.audio_out:
            audio_pos += mixer.sr * front_dt
            n = int(audio_pos)
            audio_pos -= n
            audio_chunks.append(mixer.render(n))

        # ---- Draw ---------------------------------------------------------------
        if not args.no_show or writer:
            canvas = np.zeros((canvas_size[1], canvas_size[0], 3), np.uint8)
            canvas[:view_h, :view_w] = views[0]
            canvas[:view_h, view_w:] = views[1]
            draw_panel(canvas, view_h, fused, snds, [t.color for t in cam_tracks[0]], ymap, version, active)
            if writer:
                writer.write(canvas)

        if not args.no_show:
            cv2.imshow(WINDOW, canvas)
            if show_mask:
                t = cam_tracks[active_cam][active]
                if t.mask is not None:
                    m = cv2.cvtColor(cv2.resize(t.mask, (640, 360)), cv2.COLOR_GRAY2BGR)
                    cv2.putText(m, f"{CAM_NAMES[active_cam]} - {t.name} (c = camera, b = ball)", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, t.color, 2, cv2.LINE_AA)
                    cv2.imshow("Mask", m)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key in (ord("1"), ord("2"), ord("3")):
                cv2.setTrackbarPos("Version", WINDOW, key - ord("0"))
            elif key in (ord("b"), 9) and args.balls > 1:
                active = (active + 1) % args.balls
                if show_mask:
                    write_sliders(cam_tracks[active_cam][active].settings)
                print(f"Active: Ball {active + 1}")
            elif key == ord("c"):
                active_cam = 1 - active_cam
                if show_mask:
                    write_sliders(cam_tracks[active_cam][active].settings)
                print(f"Active camera: {CAM_NAMES[active_cam]}")
            elif key == ord("m"):
                show_mask = not show_mask
                if show_mask:
                    create_mask_window(cam_tracks[active_cam][active].settings)
                else:
                    cv2.destroyWindow("Mask")
            elif key == ord("s"):
                for sl, f in zip(cam_settings, files):
                    save_settings(sl, f)
            elif key == ord("r"):
                t = cam_tracks[active_cam][active]
                t.settings.update(DEFAULT_BALLS[active])
                if show_mask:
                    write_sliders(t.settings)
                print(f"{CAM_NAMES[active_cam]} {t.name}: reset to default color")
        elif frame_idx % 50 == 0:
            parts = [f"{fb.index + 1}: x={fmt(fb.x)} y={fmt(fb.y)} z={fmt(fb.z)} [{fb.seen or '-'}]"
                     for fb in fused]
            print(f"frame {frame_idx:5d} | " + " | ".join(parts) + f" | {ymap.status}")

        frame_idx += 1

    for cam in cams:
        cam.release()
    mixer.stop()
    if args.audio_out and audio_chunks:
        from scipy.io import wavfile
        wavfile.write(args.audio_out, mixer.sr, np.concatenate(audio_chunks))
        print(f"Wrote {args.audio_out}")
    if writer:
        writer.release()
    if not args.no_show:
        cv2.destroyAllWindows()
    print(f"Done. {frame_idx} frames | {ymap.status}")
    for fb in fused:
        c = fb.counts
        print(f"  {fb.name}: front+side {c.get('front+side', 0)}, only front {c.get('front', 0)}, "
              f"only side {c.get('side', 0)}, predicted {c.get('predicted', 0)}, none {c.get('none', 0)}")


if __name__ == "__main__":
    main()

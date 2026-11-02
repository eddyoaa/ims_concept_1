# ============================================================
# BALL POSITIONS IN THE ROOM FROM SYNCED VIDEOS  (dataset)
# ============================================================
# Takes the synced videos from sync_videos.py (same start, same frame rate)
# and builds a dataset: where each ball is in the room, frame by frame.
#
# Cameras: front is needed, plus at least one more (side and/or top).
# They can stand at any angle; the names only matter for the room axes
# (x/y/z are taken from the front camera's view).
#   front : looks at the scene from the front (e.g. the Mac)
#   side  : from the side, e.g. 45-90 degrees to the front camera
#   top   : on the ceiling, looking down
#
# Step 1, once per take: pick the ball colors in every camera
#   python analyze_videos.py VIDEO_FOLDER --front mac.mp4 --side iphone_seite.mp4 --top iphone_decke.mp4 --setup
#
#   A window shows one camera at a time. Move the "Frame" slider to a frame
#   where the balls are visible, LEFT CLICK ball 1, RIGHT CLICK ball 2.
#   The circles show what the tracker finds. Keys:
#     m = mask window with sliders (active ball), b = switch active ball,
#     n / SPACE = save and go to the next camera, q = quit without saving
#
# Step 2: track and build the dataset (no window, runs on its own)
#   python analyze_videos.py VIDEO_FOLDER --ball-diameter 0.2
#   (the cameras from step 1 are remembered; --video also writes videos with markers to check)
#
# Results in VIDEO_FOLDER/analysis/:
#   balls_3d.csv   frame, time, ball, x, y, z, vx, vy, vz, seen_by   <- the dataset
#   tracks_2d.csv  raw positions per camera in pixels (for your own analysis)
#   mapping.json   how the cameras were found to stand, and how well they fit
#   check_<cam>.mp4  with --video: the camera image with the tracked balls
#   ignored_<cam>.png  places with the ball color that never move (hidden from the tracker)
#
# Room coordinates in balls_3d.csv:
#   x = left -> right, as the front camera sees it
#   y = height, grows UPWARDS
#   z = depth, grows AWAY from the front camera
#   Units: meters with --ball-diameter, otherwise ball radii. All three axes
#   use the same scale. The lowest/leftmost/nearest point of the take is 0.
#   A row needs at least two cameras that see the ball; frames seen by only
#   one camera are left out.
#
# How the cameras are matched (no calibration board needed): the ball itself
# is the calibration object. Its offset from the image center divided by its
# size in the image cancels out perspective (near = big and moves a lot,
# far = small and moves little). Then every camera is a simple projection of
# the 3D position, and the script finds where each camera stands from the
# frames where several cameras see the ball (affine structure from motion).
# Every camera is checked against the front camera first; one that doesn't
# fit (wrong blobs, strong lens distortion) is left out of 3D and reported.
#
# Limits: accuracy is a few centimeters for a ball that is fully visible.
# Best with normal (1x) lenses: an ultra-wide lens at the image border bends
# the geometry. Balls cut off by the image border or hidden in hands are
# less precise.
# ============================================================

import argparse
import csv
import itertools
import json
import os

import cv2
import numpy as np

from color_ball_tracking import (VERSION_NAMES, BallTrack, build_parser, create_mask_window,
                                 load_settings, make_mask, read_sliders, save_settings, settings_from_click,
                                 warn_overlap, write_sliders)

ROLES = ["front", "side", "top"]
OUT = "analysis"
MAX_SIDE = 1280          # frames are processed with their longer side at most this big


def parse_args():
    p = argparse.ArgumentParser(description="Ball positions in the room from synced videos")
    p.add_argument("folder", help="Folder with the synced videos (e.g. aufnahmen/take1/synced)")
    p.add_argument("--front", help="Video of the front camera (file name in the folder)")
    p.add_argument("--side", help="Video of the side camera")
    p.add_argument("--top", help="Video of the ceiling camera")
    p.add_argument("--setup", action="store_true", help="Pick the ball colors in every camera")
    p.add_argument("--balls", type=int, default=2, choices=[1, 2], help="Number of balls (default 2)")
    p.add_argument("--version", type=int, default=3, choices=[1, 2, 3], help="Detection version (default 3)")
    p.add_argument("--min-radius", type=float, default=4,
                   help="Ignore blobs smaller than this (px). Lower it if the balls look tiny (ceiling camera)")
    p.add_argument("--ball-diameter", type=float, default=None,
                   help="Ball diameter in meters (e.g. 0.07). Then the dataset is in meters")
    p.add_argument("--no-perspective", action="store_true",
                   help="Don't correct perspective with the ball size (use it if the ball size is measured badly)")
    p.add_argument("--keep-static", action="store_true",
                   help="Don't hide things with the ball color that never move (stickers, tape)")
    p.add_argument("--video", action="store_true", help="Also write check_<camera>.mp4 with the tracked balls")
    p.add_argument("--start", type=float, default=0, help="Start at this second")
    p.add_argument("--end", type=float, default=None, help="Stop at this second")
    return p.parse_args()


def tracker_args(w, h, args):
    """The settings BallTrack expects, with the defaults of color_ball_tracking.py."""
    a = build_parser().parse_args([])
    a.width, a.height = w, h
    a.min_radius = args.min_radius
    return a


def proc_size(cap):
    w, h = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    s = min(1.0, MAX_SIDE / max(w, h))
    return int(round(w * s)), int(round(h * s))


def open_video(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open {path}")
    return cap


def to_hsv(frame):
    return cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)


# ============================================================
# CONFIG: which file is which camera
# ============================================================

def load_cameras(args):
    out_dir = os.path.join(args.folder, OUT)
    cfg_path = os.path.join(out_dir, "cameras.json")
    cams = {}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cams = json.load(f)
    for r in ROLES:
        if getattr(args, r):
            cams[r] = getattr(args, r)
    if "front" not in cams:
        raise SystemExit("Which video is the front camera? Use --front FILE (and --side / --top).")
    for r, name in cams.items():
        if not os.path.exists(os.path.join(args.folder, name)):
            raise SystemExit(f"--{r} {name}: not found in {args.folder}")
    os.makedirs(out_dir, exist_ok=True)
    with open(cfg_path, "w") as f:
        json.dump(cams, f, indent=2)
    return cams, out_dir


def color_file(out_dir, role):
    return os.path.join(out_dir, f"colors_{role}.json")


# ============================================================
# STEP 1: PICK COLORS
# ============================================================

def setup_camera(role, path, settings_path, args):
    cap = open_video(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    w, h = proc_size(cap)
    settings = load_settings(settings_path)
    targs = tracker_args(w, h, args)
    win = f"Setup {role.upper()} - left click ball 1, right click ball 2, n = next"
    state = {"active": 0, "clicks": [], "mask": False}

    def on_mouse(ev, x, y, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN:
            state["clicks"].append((x, y, state["active"]))
        elif ev == cv2.EVENT_RBUTTONDOWN and args.balls > 1:
            state["clicks"].append((x, y, 1))

    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    cv2.createTrackbar("Frame", win, 0, max(n - 1, 1), lambda v: None)
    cv2.setMouseCallback(win, on_mouse)
    pos, frame = -1, None
    saved = False
    while True:
        p = cv2.getTrackbarPos("Frame", win)
        if p != pos:
            cap.set(cv2.CAP_PROP_POS_FRAMES, p)
            ok, f = cap.read()
            if ok:
                frame = cv2.resize(f, (w, h))
            pos = p
        if frame is None:
            raise SystemExit(f"{path}: could not read frames")
        hsv = to_hsv(frame)
        for x, y, b in state["clicks"]:
            settings[b].update(settings_from_click(hsv, x, y))
            print(f"{role} Ball {b + 1}: color picked at ({x}, {y})")
            if state["mask"] and b == state["active"]:
                write_sliders(settings[b])
        state["clicks"].clear()
        if state["mask"]:
            read_sliders(settings[state["active"]])

        # Show what the tracker finds in this single frame
        view = frame.copy()
        for i in range(args.balls):
            t = BallTrack(i, settings[i], targs)
            for _ in range(2):            # second step: shape checks know the ball size
                t.step(hsv, 1 / 60, args.version)
            t.draw(view, False)
            if state["mask"] and i == state["active"] and t.mask is not None:
                cv2.imshow("Mask", cv2.resize(t.mask, (640, int(640 * h / w))))
        cv2.putText(view, f"{role.upper()}  active: Ball {state['active'] + 1}  (b = switch, m = mask, "
                          f"n = save + next, q = quit)", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow(win, view)
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key in (ord("n"), ord(" "), 13):
            save_settings(settings, settings_path)
            saved = True
            break
        if key in (ord("b"), 9) and args.balls > 1:
            state["active"] = (state["active"] + 1) % args.balls
            if state["mask"]:
                write_sliders(settings[state["active"]])
        if key == ord("m"):
            state["mask"] = not state["mask"]
            if state["mask"]:
                create_mask_window(settings[state["active"]])
            else:
                cv2.destroyWindow("Mask")
    cv2.destroyAllWindows()
    cap.release()
    return saved


# ============================================================
# STATIC LOOK-ALIKES
# ============================================================

def static_mask(path, settings, balls, w, h, version, samples=60):
    """Places that have the ball color in most of the video: stickers, tape,
    posters. A flying ball is never at the same spot for long, so these are
    hidden from the tracker. (A ball that lies still for most of the take
    would be hidden too.)"""
    cap = open_video(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    count, used = np.zeros((h, w), np.float32), 0
    for idx in np.linspace(0, max(n - 1, 0), min(samples, max(n, 1))).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, f = cap.read()
        if not ok:
            continue
        hsv = to_hsv(cv2.resize(f, (w, h)))
        m = np.zeros((h, w), np.uint8)
        for i in range(balls):
            m |= make_mask(hsv, settings[i], version)
        count += m > 0
        used += 1
    cap.release()
    if used == 0:
        return None
    static = ((count / used) > 0.2).astype(np.uint8) * 255
    static = cv2.dilate(static, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    return static if static.any() else None


# ============================================================
# STEP 2a: TRACK EVERY CAMERA
# ============================================================

def track_camera(role, path, settings_path, args, out_dir):
    """Runs the color tracker over the whole video. Returns per ball arrays
    u, v (pixels), r (radius), seen (bool), plus image size and fps."""
    cap = open_video(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = proc_size(cap)
    if not os.path.exists(settings_path):
        print(f"  {role}: no colors picked yet ({settings_path}), using default colors. "
              "Run with --setup first for reliable results.")
    settings = load_settings(settings_path)
    targs = tracker_args(w, h, args)
    tracks = [BallTrack(i, settings[i], targs) for i in range(args.balls)]
    warn_overlap(tracks)
    static = None if args.keep_static else static_mask(path, settings, args.balls, w, h, args.version)
    if static is not None:
        cv2.imwrite(os.path.join(out_dir, f"ignored_{role}.png"), static)
        print(f"  {role}: ignoring {np.count_nonzero(static) / static.size * 100:.1f} % of the image "
              f"(things with the ball color that don't move, see ignored_{role}.png)")

    f0 = int(round(args.start * fps))
    f1 = n if args.end is None else min(n, int(round(args.end * fps)))
    if f0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    m = max(f1 - f0, 0)
    data = {"u": np.full((args.balls, m), np.nan), "v": np.full((args.balls, m), np.nan),
            "r": np.full((args.balls, m), np.nan), "d": np.full((args.balls, m), np.nan), "state": np.full((args.balls, m), "", dtype=object)}
    writer = None
    if args.video:
        writer = cv2.VideoWriter(os.path.join(out_dir, f"check_{role}.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    dt = 1.0 / fps
    k = 0
    while k < m:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.resize(frame, (w, h))
        hsv = to_hsv(frame)
        if static is not None:
            hsv[static > 0] = 0          # black: never matches a ball color
        for i, t in enumerate(tracks):
            t.step(hsv, dt, args.version)
            if t.pos is not None:
                data["u"][i, k], data["v"][i, k] = t.pos
                data["r"][i, k] = t.radius
                data["d"][i, k] = t.ball_width if t.ball_width > 0 else np.nan
                data["state"][i, k] = t.state
        if writer:
            for t in tracks:
                t.draw(frame, False)
            cv2.putText(frame, f"{role}  frame {f0 + k}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(frame)
        k += 1
        if k % 300 == 0:
            print(f"  {role}: {k}/{m} frames")
    cap.release()
    if writer:
        writer.release()
    for key in data:
        data[key] = data[key][:, :k]
    data.update({"w": w, "h": h, "fps": fps, "f0": f0, "n": k, "perspective": not args.no_perspective})
    seen = np.isin(data["state"], ["full", "partial"])
    print(f"  {role}: {k} frames, ball seen in " +
          ", ".join(f"Ball {i + 1}: {seen[i].mean() * 100:.0f} %" for i in range(args.balls)))
    return data


# ============================================================
# STEP 2b: FUSE THE CAMERAS INTO ROOM COORDINATES
# ============================================================
# Every camera sees the ball as a 2D point. With the perspective correction
# (offset from the image center divided by the ball radius) each camera
# becomes a simple linear projection of the 3D position:
#     p_camera = A_camera @ X + t_camera      (A: 2x3, rows = camera axes)
# The script finds all A, t and X at once from the frames where the ball is
# seen by several cameras (affine structure from motion), then makes the
# camera axes perpendicular and equally long (= real cameras), so the
# result has right angles and one scale. No calibration and no fixed
# camera angles needed.

def coord(cam):
    """2 x frames array of the ball position as one camera sees it.

    Perspective correction: a ball twice as far away moves half as much in the
    image and looks half as big. Dividing the offset from the image center by
    the ball radius cancels that out: the result is the sideways distance from
    the camera's axis in ball radii, however far away the ball is.
    Without it (--no-perspective) it is just pixels / image width."""
    if not cam["perspective"]:
        return np.stack([cam["u"] / cam["w"], cam["v"] / cam["w"]])
    r = np.where(cam["r"] > 0.5, cam["r"], np.nan)
    return np.stack([(cam["u"] - cam["w"] / 2) / r, (cam["v"] - cam["h"] / 2) / r])


def solve_points(Ms, ts, P, V):
    """3D point per column from all cameras that see it (least squares). Needs 2 cameras."""
    K = P[0].shape[1]
    X = np.full((3, K), np.nan)
    count = sum(v.astype(int) for v in V)
    for k in np.nonzero(count >= 2)[0]:
        A = np.vstack([Ms[c] for c in range(len(Ms)) if V[c][k]])
        b = np.concatenate([P[c][:, k] - ts[c] for c in range(len(Ms)) if V[c][k]])
        X[:, k] = np.linalg.lstsq(A, b, rcond=None)[0]
    return X


def solve_camera(X, p, v):
    """Camera matrix A (2x3) and offset t (2) from known 3D points."""
    ok = v & np.isfinite(X).all(axis=0)
    if ok.sum() < 8:
        return None, None
    A = np.c_[X[:, ok].T, np.ones(ok.sum())]
    sol = np.linalg.lstsq(A, p[:, ok].T, rcond=None)[0]     # 4 x 2
    return sol[:3].T, sol[3]


def metric_upgrade(Ms, ref, unit_all, quiet=False):
    """Find Q so that every camera's two axes (rows of M @ Q) are perpendicular and
    equally long, and the reference camera's axes have length 1. With the
    perspective correction every camera measures in ball radii, so all axes
    have length 1 (unit_all)."""
    def row(a, b):   # coefficients of a^T L b for symmetric L (6 unknowns)
        return [a[0] * b[0], a[0] * b[1] + a[1] * b[0], a[0] * b[2] + a[2] * b[0],
                a[1] * b[1], a[1] * b[2] + a[2] * b[1], a[2] * b[2]]
    rows, rhs = [], []
    for c, M in enumerate(Ms):
        a, b = M
        rows.append(np.subtract(row(a, a), row(b, b)))
        rhs.append(0.0)
        rows.append(row(a, b))
        rhs.append(0.0)
        if c == ref or unit_all:
            rows += [row(a, a), row(b, b)]
            rhs += [1.0, 1.0]
    l = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
    L = np.array([[l[0], l[1], l[2]], [l[1], l[3], l[4]], [l[2], l[4], l[5]]])
    w, U = np.linalg.eigh(L)
    if (w <= 0).any():
        if not quiet:
            print("  NOTE: the camera geometry is not well defined (the ball moved too little, "
                  "or too few frames seen by several cameras). Result may be skewed.")
        w = np.maximum(w, 1e-3 * max(w.max(), 1e-9))
    return U @ np.diag(np.sqrt(w))


def fuse(cams, balls, quiet=False):
    """Returns x, y, z (balls x frames), seen_by labels, frame count and info."""
    roles = list(cams)
    n = min(c["n"] for c in cams.values())
    P, V, Vany = [], [], []
    for r in roles:
        cam = cams[r]
        p = coord(cam)[:, :, :n].reshape(2, -1)                 # 2 x (balls * frames)
        seen = np.isin(cam["state"][:, :n], ["full", "partial"]).reshape(-1)
        have = np.isfinite(p).all(axis=0)
        P.append(np.where(have, p, 0.0))
        V.append(seen & have)
        Vany.append(have)
    m, K = len(roles), P[0].shape[1]
    info = {"method": "affine structure from motion with perspective correction"}

    # ---- start: the cameras that see the ball together most often --------
    best = None
    for size in range(m, 1, -1):
        for group in itertools.combinations(range(m), size):
            both = np.logical_and.reduce([V[c] for c in group])
            if both.sum() >= 30 and (best is None or both.sum() > best[1].sum() * 2):
                best = (group, both)
        if best is not None:
            break
    if best is None:
        raise SystemExit("Too few frames where at least two cameras see the ball at the same time "
                         "(need 30). Check the colors (--setup) and check_<camera>.mp4 (--video).")
    group, both = best
    W = np.vstack([P[c][:, both] for c in group])
    mean = W.mean(axis=1, keepdims=True)
    U, S, Vt = np.linalg.svd(W - mean, full_matrices=False)
    Mg = U[:, :3] * np.sqrt(S[:3])
    Ms, ts = [None] * m, [None] * m
    for i, c in enumerate(group):
        Ms[c], ts[c] = Mg[2 * i:2 * i + 2], mean[2 * i:2 * i + 2, 0]
    X = np.full((3, K), np.nan)
    X[:, both] = (np.sqrt(S[:3])[:, None] * Vt[:3])

    # ---- refine: alternate between cameras and points, drop outliers ------
    use = [v.copy() for v in V]
    for it in range(30):
        for c in range(m):
            M, t = solve_camera(X, P[c], use[c])
            if M is not None:
                Ms[c], ts[c] = M, t
        active = [c for c in range(m) if Ms[c] is not None]
        X = solve_points([Ms[c] for c in active], [ts[c] for c in active],
                         [P[c] for c in active], [use[c] for c in active])
        if it in (10, 20):
            # observations far off the common solution: probably a wrong blob
            for c in active:
                err = np.linalg.norm(Ms[c] @ X + ts[c][:, None] - P[c], axis=0)
                e = err[use[c] & np.isfinite(err)]
                if e.size:
                    use[c] &= ~(err > max(4 * np.median(e), 1e-9))
    missing = [roles[c] for c in range(m) if Ms[c] is None]
    if missing and not quiet:
        print(f"  WARNING: {', '.join(missing)} never saw the ball together with another camera, not used.")

    # ---- real cameras: right angles, one scale ----------------------------
    active = [c for c in range(m) if Ms[c] is not None]
    ref = roles.index("front") if "front" in roles and Ms[roles.index("front")] is not None else active[0]
    persp = all(cams[r]["perspective"] for r in roles)
    Q = metric_upgrade([Ms[c] for c in active], active.index(ref), persp, quiet)
    Ms = [None if M is None else M @ Q for M in Ms]

    # ---- room axes from the front camera: x right, y up, z away ----------
    a, b = Ms[ref]
    ex = a / np.linalg.norm(a)
    ey = -(b - ex * (b @ ex))
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    Rm = np.array([ex, ey, ez])
    Ms = [None if M is None else M @ Rm.T for M in Ms]

    # final points: cameras that see the ball; if fewer than 2, also predicted positions
    Xs = solve_points([Ms[c] for c in active], [ts[c] for c in active],
                      [P[c] for c in active], [use[c] for c in active])
    Xp = solve_points([Ms[c] for c in active], [ts[c] for c in active],
                      [P[c] for c in active], [Vany[c] for c in active])
    seen_cnt = sum(use[c].astype(int) for c in active)
    Xr = np.where(seen_cnt >= 2, Xs, Xp)

    # depth direction: far from the front camera = ball looks smaller there
    rf = np.where(V[ref], cams[roles[ref]]["r"][:, :n].reshape(-1), np.nan)
    ok = np.isfinite(Xr[2]) & np.isfinite(rf)
    if ok.sum() > 30 and np.std(Xr[2][ok]) > 0:
        c = float(np.corrcoef(Xr[2][ok], rf[ok])[0, 1])
        if c > 0:
            Xr[2] = -Xr[2]
            Ms = [None if M is None else M * np.array([1, 1, -1]) for M in Ms]
        if abs(c) < 0.2 and not quiet:
            print("  NOTE: the depth direction is unsure. Check that z grows away from the front camera.")

    # ---- report: how each camera is placed and how well it fits -----------
    # (camera matrices are now in room axes: x = [1,0,0], y = up, z = away)
    ey, ez = np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])
    info["cameras_found"] = {}
    for c in range(m):
        if Ms[c] is None:
            info["cameras_found"][roles[c]] = None
            continue
        a, b = Ms[c]
        view = np.cross(a, b)
        view /= np.linalg.norm(view)
        err = np.linalg.norm(Ms[c] @ Xr + ts[c][:, None] - P[c], axis=0)
        e = err[use[c] & np.isfinite(err)]
        info["cameras_found"][roles[c]] = {
            "angle_to_front_deg": round(float(np.degrees(np.arccos(abs(np.clip(view @ ez, -1, 1))))), 1),
            "looks_down_deg": round(float(np.degrees(np.arcsin(np.clip(abs(view @ ey), 0, 1)))), 1),
            "axis_lengths": [round(float(np.linalg.norm(a)), 3), round(float(np.linalg.norm(b)), 3)],
            "axes_angle_deg": round(float(np.degrees(np.arccos(np.clip(
                a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))), 1),
            "median_error": round(float(np.median(e)), 3) if e.size else None,
            "frames_used": int(use[c].sum()),
        }

    x, y, z = (Xr[i].reshape(balls, n) for i in range(3))
    x, y, z = x.copy(), y.copy(), z.copy()
    for arr in (x, y, z):
        if np.isfinite(arr).any():
            arr -= np.nanmin(arr)

    labels = np.full(K, "", dtype=object)
    for c in active:
        labels = np.where(use[c], np.where(labels == "", roles[c], labels + "+" + roles[c]), labels)
    labels = np.where(np.isfinite(Xr[0]) & (seen_cnt < 2), "predicted", labels)
    labels = np.where(np.isfinite(Xr[0]), labels, "")
    return x, y, z, labels.reshape(balls, n), n, info


def choose_cameras(data, balls):
    """Check every camera against the front camera. A camera whose positions
    don't fit together with the front camera (wrong blobs, strong lens
    distortion, ...) would bend the whole result, so it is left out of 3D."""
    others = [r for r in data if r != "front"]
    if len(others) < 2:
        return list(data), {}
    errors = {}
    for r in others:
        try:
            *_, info = fuse({"front": data["front"], r: data[r]}, balls, quiet=True)
        except SystemExit:
            errors[r] = None
            continue
        found = info["cameras_found"]
        errors[r] = max(found[k]["median_error"] or 0 for k in found if found[k])
    known = [e for e in errors.values() if e is not None]
    if not known:
        return list(data), errors
    limit = max(0.5, 2 * min(known))
    keep = ["front"] + [r for r in others if errors[r] is not None and errors[r] <= limit]
    for r in others:
        e = errors[r]
        state = "ok" if r in keep else "LEFT OUT of 3D (doesn't fit the front camera)"
        print(f"  front + {r}: error {('-' if e is None else f'{e:.2f}')} ball radii -> {state}")
    return keep, errors


def velocity(a, fps):
    v = np.full_like(a, np.nan)
    v[:, 1:-1] = (a[:, 2:] - a[:, :-2]) * fps / 2
    return v


# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_args()
    cams, out_dir = load_cameras(args)
    print("Cameras: " + ", ".join(f"{r} = {f}" for r, f in cams.items()))

    if args.setup:
        for role, name in cams.items():
            if not setup_camera(role, os.path.join(args.folder, name), color_file(out_dir, role), args):
                print("Setup stopped.")
                return
        print("\nColors saved. Now run without --setup:")
        print(f"  python analyze_videos.py {args.folder}")
        return

    print(f"\nTracking ({VERSION_NAMES[args.version]})...")
    data = {}
    for role, name in cams.items():
        data[role] = track_camera(role, os.path.join(args.folder, name), color_file(out_dir, role), args, out_dir)
    fps = data["front"]["fps"]
    f0 = data["front"]["f0"]
    fps_set = {round(d["fps"], 2) for d in data.values()}
    if len(fps_set) > 1:
        print(f"  WARNING: the videos have different frame rates {fps_set}. Use the output of sync_videos.py.")

    # Raw 2D tracks
    path2d = os.path.join(out_dir, "tracks_2d.csv")
    with open(path2d, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["frame", "time_s", "camera", "ball", "x_px", "y_px", "radius_px", "width_px", "state"])
        for role, d in data.items():
            for k in range(d["n"]):
                for b in range(args.balls):
                    if d["state"][b, k]:
                        wr.writerow([f0 + k, f"{(f0 + k) / fps:.4f}", role, b + 1, f"{d['u'][b, k]:.1f}",
                                     f"{d['v'][b, k]:.1f}", f"{d['r'][b, k]:.1f}", f"{d['d'][b, k]:.1f}", d["state"][b, k]])

    print("\nMatching the cameras...")
    keep, pair_errors = choose_cameras(data, args.balls)
    x, y, z, labels, n, info = fuse({r: data[r] for r in keep}, args.balls)
    info["pair_errors_with_front"] = pair_errors
    info["used_for_3d"] = keep
    if args.no_perspective:
        info["units"] = "relative: 1.0 = width of the front camera image"
    elif args.ball_diameter:
        for a in (x, y, z):
            a *= args.ball_diameter / 2          # ball radii -> meters
        info["units"] = "meters (from --ball-diameter)"
    else:
        info["units"] = "ball radii (use --ball-diameter to get meters)"
    info["axes"] = "x right (front camera view), y up, z away from the front camera"
    vx, vy, vz = velocity(x, fps), velocity(y, fps), velocity(z, fps)

    path3d = os.path.join(out_dir, "balls_3d.csv")
    rows = 0

    def fmt(v):
        return "" if not np.isfinite(v) else f"{v:.4f}"

    with open(path3d, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["frame", "time_s", "ball", "x", "y", "z", "vx", "vy", "vz", "seen_by"])
        for k in range(n):
            for b in range(args.balls):
                if not labels[b, k]:
                    continue
                wr.writerow([f0 + k, f"{(f0 + k) / fps:.4f}", b + 1, fmt(x[b, k]), fmt(y[b, k]), fmt(z[b, k]),
                             fmt(vx[b, k]), fmt(vy[b, k]), fmt(vz[b, k]), labels[b, k]])
                rows += 1

    info["cameras"] = cams
    info["fps"] = fps
    with open(os.path.join(out_dir, "mapping.json"), "w") as f:
        json.dump(info, f, indent=2)

    print("\nCameras as found from the ball positions (check if this matches your setup):")
    for role, v in info["cameras_found"].items():
        if v is None:
            print(f"  {role:5s}: not used")
            continue
        print(f"  {role:5s}: {v['angle_to_front_deg']:5.1f} deg to the front camera, looks down "
              f"{v['looks_down_deg']:4.1f} deg, error {v['median_error']} ball radii, {v['frames_used']} frames")
    print(f"\nDone: {rows} rows, units: {info['units']}")
    print(f"  {path3d}")
    print(f"  {path2d}")
    for b in range(args.balls):
        got = labels[b] != ""
        full3d = got & np.isfinite(x[b]) & np.isfinite(y[b]) & np.isfinite(z[b])
        print(f"  Ball {b + 1}: tracked in {got.mean() * 100:.0f} % of the frames, "
              f"full 3D in {full3d.mean() * 100:.0f} %")


if __name__ == "__main__":
    main()

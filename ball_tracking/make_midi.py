# ============================================================
# MIDI CUES FOR THE VIDEO  (from the analysis of analyze_videos.py)
# ============================================================
# Turns the ball data into a MIDI file that lines up with the video:
# load it into a DAW (Ableton, Logic, ...) at 120 BPM starting at bar 1,
# put the video at 0:00, and every cue sits on the right frame.
#
#   python make_midi.py "../Video cutting"
#
# Needs VIDEO_FOLDER/analysis/ from analyze_videos.py. Writes:
#   analysis/ball_cues.mid   the MIDI file
#   analysis/cues.csv        the same events as a list (time, frame, what)
#
# MIDI channel 1 (same CCs as beschleunigung/midi.py):
#   Note C3 (48)  throw: on when the ball leaves the hand, off when it is caught
#                 velocity = how fast the throw is
#   Note D3 (50)  short note at the highest point of the throw
#   Note E3 (52)  short note at the catch
#   CC 16  x  (left -> right, front camera view)
#   CC 17  y  (height, up = 127)
#   CC 18  z  (depth, away from the front camera = 127)
#   CC 7   speed of the ball (still = 0)
#   Markers "Wurf 1", "Wurf 2", ... in the timeline
#
# A throw is found where the ball moves faster than --threshold ball radii
# per second (held ~0-10, flying ~20-60) for at least --min-flight seconds.
# ============================================================

import argparse
import csv
import json
import os
import warnings

import numpy as np

PPQ = 480
BPM = 120
TICKS_PER_S = PPQ * BPM / 60          # 960
CH = 0                                # MIDI channel 1
NOTE_THROW, NOTE_APEX, NOTE_CATCH = 48, 50, 52
CC_X, CC_Y, CC_Z, CC_SPEED = 16, 17, 18, 7


def parse_args():
    p = argparse.ArgumentParser(description="MIDI cues from the ball analysis")
    p.add_argument("folder", help="Video folder with analysis/ from analyze_videos.py")
    p.add_argument("--ball", type=int, default=1, help="Which ball (default 1)")
    p.add_argument("--threshold", type=float, default=12,
                   help="Speed in ball radii per second above which the ball counts as flying (default 12)")
    p.add_argument("--min-flight", type=float, default=0.25, help="Shortest throw in seconds (default 0.25)")
    p.add_argument("--out", default="ball_cues.mid", help="Name of the MIDI file (default ball_cues.mid)")
    return p.parse_args()


def load_2d(path, ball, n):
    """Per camera: u, v, r arrays (NaN where the camera doesn't see the ball)."""
    cams = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            if int(row["ball"]) != ball or row["state"] not in ("full", "partial"):
                continue
            c = cams.setdefault(row["camera"], {k: np.full(n, np.nan) for k in "uvr"})
            k = int(row["frame"])
            if k < n:
                c["u"][k], c["v"][k], c["r"][k] = float(row["x_px"]), float(row["y_px"]), float(row["radius_px"])
    return cams


def load_3d(path, ball, n):
    xyz = np.full((3, n), np.nan)
    with open(path) as f:
        for row in csv.DictReader(f):
            k = int(row["frame"])
            if int(row["ball"]) == ball and k < n and row["x"]:
                xyz[:, k] = [float(row["x"]), float(row["y"]), float(row["z"])]
    return xyz


def fill(a, max_gap):
    """Bridge gaps up to max_gap frames linearly, hold the last value after longer gaps."""
    a = a.copy()
    ok = np.isfinite(a)
    if not ok.any():
        return np.zeros_like(a)
    idx = np.arange(len(a))
    lin = np.interp(idx, idx[ok], a[ok])
    last = np.maximum.accumulate(np.where(ok, idx, -1))
    nxt = np.minimum.accumulate(np.where(ok, idx, len(a))[::-1])[::-1]
    short = (nxt - last <= max_gap) & (last >= 0) & (nxt < len(a))
    held = a[np.clip(last, 0, None)]
    held[last < 0] = a[ok][0]
    return np.where(ok, a, np.where(short, lin, held))


def to_cc(a):
    lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
    return np.clip(np.round((a - lo) / max(hi - lo, 1e-9) * 127), 0, 127).astype(int)


def find_throws(speed, fps, threshold, min_frames):
    fl = speed > threshold
    segs, k, n = [], 0, len(fl)
    while k < n:
        if fl[k]:
            j = k
            while j < n and fl[j]:
                j += 1
            if segs and k - segs[-1][1] <= 3:      # tiny gap: same throw
                segs[-1][1] = j
            else:
                segs.append([k, j])
            k = j
        else:
            k += 1
    return [s for s in segs if s[1] - s[0] >= min_frames]


def main():
    args = parse_args()
    import mido     # only needed here; pip install mido

    an = os.path.join(args.folder, "analysis")
    with open(os.path.join(an, "mapping.json")) as f:
        fps = json.load(f)["fps"]
    with open(os.path.join(an, "tracks_2d.csv")) as f:
        n = max(int(r["frame"]) for r in csv.DictReader(f)) + 1
    cams = load_2d(os.path.join(an, "tracks_2d.csv"), args.ball, n)
    xyz = load_3d(os.path.join(an, "balls_3d.csv"), args.ball, n)

    # Speed in ball radii per second: the same for near and far cameras.
    speeds = [np.hypot(np.gradient(c["u"]), np.gradient(c["v"])) * fps / c["r"] for c in cams.values()]
    with np.errstate(all="ignore"):
        with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # frames no camera sees
        speed = np.nanmedian(np.array(speeds), axis=0)
    speed = np.convolve(fill(speed, int(fps)), np.ones(3) / 3, "same")

    # Height: 3D where known; where not (ball above the front camera's view),
    # the side camera's image height, matched onto the 3D height.
    y = xyz[1].copy()
    side = cams.get("side")
    if side is not None:
        sv = -side["v"]
        both = np.isfinite(sv) & np.isfinite(y)
        if both.sum() > 30:
            k, d = np.polyfit(sv[both], y[both], 1)
            y = np.where(np.isfinite(y), y, k * sv + d)
    gap = int(0.5 * fps)
    ccs = {CC_X: to_cc(fill(xyz[0], gap)), CC_Y: to_cc(fill(y, gap)), CC_Z: to_cc(fill(xyz[2], gap)),
           CC_SPEED: np.clip(np.round(speed / 60 * 127), 0, 127).astype(int)}

    throws = find_throws(speed, fps, args.threshold, max(2, int(round(args.min_flight * fps))))

    # ---- events (seconds) -----------------------------------------------------
    events = []        # (time_s, order, mido message)
    cues = []
    hv = side["v"] if side is not None else -y
    for i, (a, b) in enumerate(throws, 1):
        seg = hv[a:b]
        apex = a + int(np.nanargmin(seg)) if np.isfinite(seg).any() else (a + b) // 2
        peak = float(np.nanmax(speed[a:b]))
        vel = int(np.clip(40 + (peak - args.threshold) / 50 * 87, 1, 127))
        t0, ta, t1 = a / fps, apex / fps, b / fps
        events += [(t0, 1, mido.MetaMessage("marker", text=f"Wurf {i}")),
                   (t0, 2, mido.Message("note_on", channel=CH, note=NOTE_THROW, velocity=vel)),
                   (t1, 0, mido.Message("note_off", channel=CH, note=NOTE_THROW, velocity=0)),
                   (ta, 2, mido.Message("note_on", channel=CH, note=NOTE_APEX, velocity=100)),
                   (ta + 0.1, 0, mido.Message("note_off", channel=CH, note=NOTE_APEX, velocity=0)),
                   (t1, 2, mido.Message("note_on", channel=CH, note=NOTE_CATCH, velocity=100)),
                   (t1 + 0.1, 0, mido.Message("note_off", channel=CH, note=NOTE_CATCH, velocity=0))]
        cues += [(t0, a, f"Wurf {i}: Ball fliegt los", vel), (ta, apex, f"Wurf {i}: höchster Punkt", ""),
                 (t1, b, f"Wurf {i}: Ball gefangen", "")]
    last = {}
    for k in range(n):
        for cc, vals in ccs.items():
            if last.get(cc) != vals[k]:
                events.append((k / fps, 3, mido.Message("control_change", channel=CH, control=cc,
                                                        value=int(vals[k]))))
                last[cc] = vals[k]

    # ---- write MIDI -------------------------------------------------------------
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="Ball", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM), time=0))
    now = 0
    for t, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        tick = int(round(t * TICKS_PER_S))
        track.append(msg.copy(time=tick - now))
        now = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    out = os.path.join(an, args.out)
    mid.save(out)

    with open(os.path.join(an, "cues.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "mm:ss:frames", "frame", "cue", "velocity"])
        for t, fr, what, vel in cues:
            tc = f"{int(t // 60):02d}:{int(t % 60):02d}:{int(round((t % 1) * fps)):02d}"
            w.writerow([f"{t:.3f}", tc, fr, what, vel])

    print(f"{len(throws)} throws found:")
    for i, (a, b) in enumerate(throws, 1):
        print(f"  Wurf {i:2d}: {a / fps:6.2f} s -> {b / fps:6.2f} s  ({(b - a) / fps:.2f} s in the air)")
    print(f"\nWrote {out}  (load at {BPM} BPM, start at bar 1 = video 0:00)")
    print(f"      {os.path.join(an, 'cues.csv')}")


if __name__ == "__main__":
    main()

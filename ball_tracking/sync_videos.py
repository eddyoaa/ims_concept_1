# ============================================================
# SYNC VIDEOS FROM SEVERAL CAMERAS BY THEIR SOUND
# ============================================================
# Put all recordings of one take into one folder (e.g. Mac + 2 iPhones),
# then run:
#
#   python sync_videos.py aufnahmen/
#
# The script finds the time offset between the videos from their audio
# (a clap or a ball hitting the floor, heard by every camera), cuts all
# videos to the time span they share and writes them with the same start,
# the same length and the same frame rate:
#
#   aufnahmen/synced/<name>.mp4     one synced video per camera
#   aufnahmen/synced/preview.mp4    all cameras side by side, to check
#   aufnahmen/synced/offsets.json   the offsets that were found
#
# Frame N is then the same moment in every synced video, so the files can
# go straight into the trackers, e.g.
#   python multicam_ball_tracking.py --source synced/mac.mp4 --side synced/iphone_seite.mp4
#
# How it works: the audio of each video is compared with the reference video
# (GCC-PHAT cross-correlation). This finds sharp sounds like claps very
# precisely (well below one frame), even when the microphones sound different.
# If you clapped at the end too, the script also checks the end and reports
# whether the videos drift apart over time.
#
# Options:
#   --fps 60                 frame rate of the synced videos (default 60)
#   --ref mac.mov            reference video (default: first file by name)
#   --window 60              seconds at the start that are searched for the clap.
#                            Increase it if the cameras were started far apart.
#   --shift iphone_decke.mov=0.017
#                            manual correction in seconds (repeatable). Positive
#                            = this video's content appears later in the output
#                            (the cut starts earlier in this file).
#   --no-preview             don't write preview.mp4
#   --only-offsets           only find the offsets, don't write videos
#
# Needs ffmpeg (Mac: brew install ffmpeg) and numpy.
# ============================================================

import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np

VIDEO_EXT = (".mov", ".mp4", ".m4v", ".avi", ".mkv")
SR = 16000          # audio sample rate for the comparison
OUT_DIR = "synced"


def parse_args():
    p = argparse.ArgumentParser(description="Sync videos of several cameras by their sound")
    p.add_argument("folder", help="Folder with the videos of one take")
    p.add_argument("--fps", type=float, default=60, help="Frame rate of the synced videos (default 60)")
    p.add_argument("--ref", default=None, help="Reference video (file name). Default: first by name")
    p.add_argument("--window", type=float, default=60,
                   help="Seconds at the start of each video searched for the clap (default 60)")
    p.add_argument("--shift", action="append", default=[], metavar="FILE=SECONDS",
                   help="Manual correction for one video in seconds (repeatable)")
    p.add_argument("--no-preview", action="store_true", help="Don't write preview.mp4")
    p.add_argument("--only-offsets", action="store_true", help="Only find the offsets, write no videos")
    p.add_argument("--crf", type=int, default=18, help="Video quality (H.264 CRF, lower = better, default 18)")
    return p.parse_args()


# ============================================================
# FFMPEG HELPERS
# ============================================================

def need(tool):
    if shutil.which(tool) is None:
        raise SystemExit(f"'{tool}' not found. Install ffmpeg first (Mac: brew install ffmpeg).")


def probe(path):
    """Duration, video start, frame rate and HDR info of a file."""
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_format", "-show_streams", path],
                         capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    fmt_start = float(info["format"].get("start_time", 0) or 0)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if video is None:
        raise SystemExit(f"{path}: no video stream")
    if audio is None:
        raise SystemExit(f"{path}: no audio. Syncing needs sound in every video "
                         "(QuickTime on the Mac: choose a microphone in the record menu).")
    num, den = video.get("avg_frame_rate", "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    v_start = float(video.get("start_time", fmt_start) or fmt_start)
    duration = float(video.get("duration") or info["format"]["duration"])
    hdr = video.get("color_transfer") in ("arib-std-b67", "smpte2084")
    return {"v_start": v_start - fmt_start, "duration": duration, "fps": fps, "hdr": hdr}


def load_audio(path):
    """Mono audio at SR. Sample 0 is time 0 of ffmpeg's timeline for this file
    (silence is padded if the audio starts a bit after that)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
                          "-af", "aresample=async=1:first_pts=0", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


# ============================================================
# FINDING THE OFFSET
# ============================================================

def gcc_phat(a, b, max_lag):
    """Lag in samples so that a[n] ~ b[n - lag], plus a confidence value.

    PHAT weighting keeps only the phase of the spectrum: sharp sounds (claps)
    give one clear peak, different microphone colors don't matter much.
    """
    n = 1
    while n < len(a) + len(b):
        n *= 2
    A = np.fft.rfft(a, n)
    B = np.fft.rfft(b, n)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-12
    cc = np.fft.irfft(R, n)
    max_lag = int(min(max_lag, n // 2 - 1))
    cc = np.concatenate((cc[-max_lag:], cc[:max_lag + 1]))   # lags -max_lag .. +max_lag
    i = int(np.argmax(cc))
    peak = cc[i]
    # Confidence: peak compared with the best peak elsewhere (outside +-20 ms)
    guard = int(0.02 * SR)
    rest = cc.copy()
    rest[max(0, i - guard):i + guard + 1] = 0
    second = float(np.max(rest)) if rest.size else 0.0
    # Sub-sample precision: fit a parabola through the peak and its neighbors
    frac = 0.0
    if 0 < i < len(cc) - 1:
        y0, y1, y2 = cc[i - 1], cc[i], cc[i + 1]
        d = y0 - 2 * y1 + y2
        if d != 0:
            frac = 0.5 * (y0 - y2) / d
    lag = i - max_lag + frac
    return float(lag), float(peak / max(second, 1e-9))


def segment(x, t0, t1):
    i0, i1 = max(0, int(round(t0 * SR))), max(0, int(round(t1 * SR)))
    return x[i0:i1]


# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_args()
    need("ffmpeg")
    need("ffprobe")

    folder = args.folder
    names = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(VIDEO_EXT) and not f.startswith("."))
    if len(names) < 2:
        raise SystemExit(f"Need at least 2 videos in '{folder}', found {len(names)}.")
    ref = args.ref or names[0]
    if ref not in names:
        raise SystemExit(f"--ref {ref}: not in {names}")
    names.remove(ref)
    names.insert(0, ref)

    shifts = {}
    for s in args.shift:
        if "=" not in s:
            raise SystemExit(f"--shift {s}: use FILE=SECONDS, e.g. --shift iphone.mov=0.017")
        k, v = s.split("=", 1)
        if k not in names:
            raise SystemExit(f"--shift {k}: not in {names}")
        shifts[k] = float(v)

    print(f"Videos ({len(names)}), reference: {ref}")
    vids = {}
    for n in names:
        path = os.path.join(folder, n)
        info = probe(path)
        info["audio"] = load_audio(path)
        vids[n] = info
        print(f"  {n}: {info['duration']:.1f} s, {info['fps']:.2f} fps")
        if info["hdr"]:
            print(f"    WARNING: {n} is HDR video. Colors will look pale in the synced file.")
            print("    Next time switch HDR off: Settings > Camera > Record Video > HDR Video.")

    # delay[n]: an event at time t in the reference happens at t + delay[n] in video n
    # (times relative to the first video frame of each file)
    print("\nFinding offsets...")
    delay = {ref: 0.0}
    ref_audio = vids[ref]["audio"]
    low_conf = False
    for n in names[1:]:
        a = vids[n]["audio"]
        w = args.window
        lag, conf = gcc_phat(a[:int(w * SR)], ref_audio[:int(w * SR)], max_lag=w * SR)
        # audio lag -> video lag: correct for where the first video frame sits in each file
        d = lag / SR - vids[n]["v_start"] + vids[ref]["v_start"]
        d -= shifts.get(n, 0.0)
        delay[n] = d
        flag = "" if conf >= 1.5 else "   <- UNSURE"
        low_conf |= conf < 1.5
        print(f"  {n}: {d:+.3f} s relative to {ref}  (confidence {conf:.1f}){flag}")
    if low_conf:
        print("  An offset is unsure: no clear common sound found. Clap loudly near all cameras,")
        print("  or increase --window if the cameras were started far apart.")

    # Common time span, in reference time
    start = max(-delay[n] for n in names)
    end = min(vids[n]["duration"] - delay[n] for n in names)
    length = end - start
    if length <= 0:
        raise SystemExit("The videos don't overlap in time. Check the offsets (try --window).")
    print(f"\nCommon part: {length:.1f} s")

    # Drift check at the end of the common part (if you clapped there too)
    check = min(20.0, length / 3)
    if check >= 3:
        print("Checking the end for drift...")
        for n in names[1:]:
            a0 = vids[n]["v_start"]
            r0 = vids[ref]["v_start"]
            t1 = end - check
            seg_ref = segment(ref_audio, t1 + r0, end + r0)
            seg_n = segment(vids[n]["audio"], t1 + delay[n] + a0, end + delay[n] + a0)
            m = min(len(seg_ref), len(seg_n))
            if m < SR:
                continue
            lag, conf = gcc_phat(seg_n[:m], seg_ref[:m], max_lag=0.5 * SR)
            drift_ms = lag / SR * 1000
            frame_ms = 1000 / args.fps
            if conf < 1.5:
                print(f"  {n}: no clear sound at the end, drift not checked")
            elif abs(drift_ms) > frame_ms / 2:
                print(f"  {n}: drift {drift_ms:+.1f} ms at the end (more than half a frame)")
            else:
                print(f"  {n}: ok ({drift_ms:+.1f} ms at the end)")

    out_dir = os.path.join(folder, OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    result = {
        "reference": ref,
        "fps": args.fps,
        "length_s": round(length, 4),
        "videos": {n: {"delay_s": round(delay[n], 4),
                       "cut_from_s": round(start + delay[n], 4),
                       "manual_shift_s": shifts.get(n, 0.0),
                       "output": os.path.splitext(n)[0] + ".mp4"} for n in names},
    }
    with open(os.path.join(out_dir, "offsets.json"), "w") as f:
        json.dump(result, f, indent=2)
    if args.only_offsets:
        print(f"\nOffsets saved to {os.path.join(out_dir, 'offsets.json')}")
        return

    # Cut and convert. trim works on ffmpeg's timeline, where the first video
    # frame of the file sits at v_start.
    print(f"\nWriting synced videos ({args.fps:g} fps) to {out_dir}/ ...")
    outputs = []
    n_frames = int(length * args.fps)   # same number of frames in every output
    for n in names:
        t0 = start + delay[n] + vids[n]["v_start"]
        out = os.path.join(out_dir, os.path.splitext(n)[0] + ".mp4")
        vf = f"trim=start={t0:.6f}:duration={length:.6f},setpts=PTS-STARTPTS,fps={args.fps:g}"
        af = (f"aresample=async=1:first_pts=0,atrim=start={t0:.6f}:duration={length:.6f},"
              f"asetpts=PTS-STARTPTS")
        cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-i", os.path.join(folder, n),
               "-vf", vf, "-af", af, "-frames:v", str(n_frames), "-c:v", "libx264", "-preset", "fast", "-crf", str(args.crf),
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
        print(f"  {n} -> {out}")
        subprocess.run(cmd, check=True)
        outputs.append(out)

    if not args.no_preview:
        preview = os.path.join(out_dir, "preview.mp4")
        print(f"  preview -> {preview}")
        cmd = ["ffmpeg", "-v", "error", "-stats", "-y"]
        for o in outputs:
            cmd += ["-i", o]
        scale = ";".join(f"[{i}:v]scale=-2:360,setsar=1[v{i}]" for i in range(len(outputs)))
        stack = "".join(f"[v{i}]" for i in range(len(outputs)))
        fc = f"{scale};{stack}hstack=inputs={len(outputs)}[v]"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "26", "-c:a", "aac", preview]
        subprocess.run(cmd, check=True)

    print("\nDone. Check preview.mp4: step frame by frame through the clap,")
    print("the hands should meet in the same frame in every picture.")
    print("If one camera is a frame off: run again with --shift <file>=<seconds> "
          f"(one frame = {1 / args.fps:.4f} s).")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg failed: {e}")

#!/usr/bin/env python3
"""
TikTok Optimizer

Two modes:
  retime    (default for H.264 files) Copies your video stream untouched and only
            rewrites its timestamps (2x longer, half the frame rate label). No
            re-encoding, so zero quality loss and it finishes in seconds.
  reencode  Re-encodes to a clean high-bitrate H.264/HEVC MP4. Used automatically
            for files that are not H.264 (e.g. HEVC), or when you ask for it.

Requires: Python 3.8+ and FFmpeg (ffmpeg + ffprobe) in PATH.

Examples:
    python tiktok_optimizer.py video.mp4
    python tiktok_optimizer.py video.mp4 --audio drop
    python tiktok_optimizer.py video.mp4 --mode reencode --preset 1080p --fps 30
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PRESETS = {
    "1080p": {"long": 1920, "short": 1080, "bitrate": 15, "max_fps": 60},
    "4k":    {"long": 3840, "short": 2160, "bitrate": 40, "max_fps": 60},
    "source": {"long": None, "short": None, "bitrate": 25, "max_fps": 120},
}


def check_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(f"Error: '{tool}' not found. Install FFmpeg and add it to PATH.\n"
                     "Download: https://ffmpeg.org/download.html")


def probe(path: Path) -> dict:
    cmd = ["ffprobe", "-v", "error",
           "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt",
           "-show_entries", "format=duration,size", "-of", "json", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffprobe failed on {path.name}:\n{r.stderr}")
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        sys.exit(f"No video stream found in {path.name}")
    num, den = v["r_frame_rate"].split("/")
    return {
        "codec": v.get("codec_name", "?"),
        "pix_fmt": v.get("pix_fmt", "?"),
        "width": int(v["width"]), "height": int(v["height"]),
        "fps": float(num) / float(den) if float(den) else 30.0,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "duration": float(data["format"].get("duration", 0)),
        "size_mb": int(data["format"].get("size", 0)) / (1024 * 1024),
    }


def fmt_time(s: float) -> str:
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


def atempo_chain(stretch: float) -> str:
    """atempo only accepts 0.5-100, so chain filters for big stretches."""
    parts, remaining = [], 1.0 / stretch
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def build_scale_filter(info: dict, preset: dict):
    if preset["long"] is None:
        return None
    w, h = info["width"], info["height"]
    portrait = h > w
    max_w, max_h = (preset["short"], preset["long"]) if portrait else (preset["long"], preset["short"])
    if w <= max_w and h <= max_h:
        return None
    return f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"


def retime_cmd(path, out, info, args):
    tag = "hvc1" if info["codec"] in ("hevc", "h265") else "avc1"
    cmd = ["ffmpeg", "-y" if args.overwrite else "-n", "-hide_banner",
           "-itsscale:v", str(args.stretch), "-i", str(path),
           "-map", "0:v:0", "-c:v", "copy", "-tag:v", tag]
    if args.audio == "keep" and info["has_audio"]:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "320k", "-filter:a", atempo_chain(args.stretch)]
    else:
        cmd += ["-an"]
    return cmd + ["-movflags", "+faststart", str(out)]


def reencode_cmd(path, out, info, args):
    preset = PRESETS[args.preset]
    fps = args.fps if args.fps else min(round(info["fps"]), preset["max_fps"])
    br = args.bitrate if args.bitrate else preset["bitrate"]
    cmd = ["ffmpeg", "-y" if args.overwrite else "-n", "-hide_banner", "-i", str(path)]
    if args.codec == "hevc":
        cmd += ["-c:v", "libx265", "-tag:v", "hvc1", "-preset", args.speed]
    else:
        cmd += ["-c:v", "libx264", "-profile:v", "high", "-preset", args.speed]
    cmd += ["-b:v", f"{br}M", "-maxrate", f"{round(br * 1.5, 1)}M", "-bufsize", f"{br * 2}M",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-fps_mode", "cfr"]
    scale = build_scale_filter(info, preset)
    if scale:
        cmd += ["-vf", scale]
    cmd += ["-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    return cmd, fps, br


def process(path: Path, args) -> None:
    info = probe(path)
    out = path.with_name(f"{path.stem}_tiktok.mp4")
    if out.exists() and not args.overwrite:
        print(f"Skipping {path.name}: {out.name} already exists (use --overwrite)")
        return

    mode = args.mode
    if mode == "auto":
        ok = info["codec"] == "h264" and info["pix_fmt"] == "yuv420p"
        mode = "retime" if ok else "reencode"
        if not ok:
            print(f"Note: {info['codec']}/{info['pix_fmt']} source, so re-encoding to H.264.")

    print(f"\n=== {path.name} ===")
    print(f"Source : {info['width']}x{info['height']} @ {info['fps']:.2f}fps, {info['codec']}, "
          f"{info['size_mb']:.1f} MB, {fmt_time(info['duration'])}")

    if mode == "retime":
        print(f"Mode   : retime (video copied, no quality loss), {args.stretch:g}x length, "
              f"audio {'slowed to match' if args.audio == 'keep' and info['has_audio'] else 'removed'}")
        cmd = retime_cmd(path, out, info, args)
    else:
        cmd, fps, br = reencode_cmd(path, out, info, args)
        print(f"Mode   : re-encode, {fps}fps, {br} Mbps {args.codec.upper()}")

    if subprocess.run(cmd).returncode != 0:
        print(f"Failed: {path.name}")
        return

    o = probe(out)
    print(f"Done   : {out.name}  {o['width']}x{o['height']} @ {o['fps']:.0f}fps, "
          f"{fmt_time(o['duration'])}, {o['size_mb']:.1f} MB")


def main():
    p = argparse.ArgumentParser(description="Optimize videos for TikTok upload.")
    p.add_argument("files", nargs="+", help="Video file(s)")
    p.add_argument("--mode", choices=["auto", "retime", "reencode"], default="auto",
                   help="auto (default): retime for H.264 files, re-encode otherwise")
    p.add_argument("--stretch", type=float, default=2.0, help="retime: length multiplier (default 2)")
    p.add_argument("--audio", choices=["keep", "drop"], default="keep",
                   help="retime: keep = audio slowed to match (default), drop = no audio")
    p.add_argument("--preset", choices=PRESETS.keys(), default="1080p", help="reencode: resolution limit")
    p.add_argument("--fps", type=int, help="reencode: force fps")
    p.add_argument("--bitrate", type=float, help="reencode: video bitrate in Mbps")
    p.add_argument("--codec", choices=["h264", "hevc"], default="h264", help="reencode: output codec")
    p.add_argument("--speed", default="slow", choices=["ultrafast", "fast", "medium", "slow", "slower"],
                   help="reencode: encoder preset")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs")
    args = p.parse_args()

    check_ffmpeg()
    for f in args.files:
        fp = Path(f)
        if fp.is_file():
            process(fp, args)
        else:
            print(f"Not found: {f}")

    print("\nUpload on TikTok web with 'Upload HD' on and visibility set to Everyone.")


if __name__ == "__main__":
    main()

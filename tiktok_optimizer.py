#!/usr/bin/env python3
"""
TikTok Optimizer - re-encodes videos to a clean, high-bitrate H.264/HEVC MP4
so TikTok has the best possible source to work with.

Requires: Python 3.8+ and FFmpeg (ffmpeg + ffprobe) available in PATH.

Usage:
    python tiktok_optimizer.py video.mp4
    python tiktok_optimizer.py video.mp4 --preset 4k
    python tiktok_optimizer.py *.mp4 --preset 1080p --fps 60
    python tiktok_optimizer.py video.mov --bitrate 25 --codec hevc

You can also drag and drop a video file onto this script on Windows.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Preset: long-edge / short-edge limits, default video bitrate (Mbps), max fps
PRESETS = {
    "1080p": {"long": 1920, "short": 1080, "bitrate": 15, "max_fps": 60},
    "4k":    {"long": 3840, "short": 2160, "bitrate": 40, "max_fps": 60},
    "source": {"long": None, "short": None, "bitrate": 25, "max_fps": 120},
}


def check_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit(
                f"Error: '{tool}' not found. Install FFmpeg and make sure it is in your PATH.\n"
                "Download: https://ffmpeg.org/download.html"
            )


def probe(path: Path) -> dict:
    """Return basic info about the first video stream."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,bit_rate",
        "-show_entries", "format=duration,size",
        "-of", "json", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"ffprobe failed on {path.name}:\n{result.stderr}")
    data = json.loads(result.stdout)
    if not data.get("streams"):
        sys.exit(f"No video stream found in {path.name}")
    s = data["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return {
        "codec": s.get("codec_name", "?"),
        "width": int(s["width"]),
        "height": int(s["height"]),
        "fps": fps,
        "duration": float(data["format"].get("duration", 0)),
        "size_mb": int(data["format"].get("size", 0)) / (1024 * 1024),
    }


def build_scale_filter(info: dict, preset: dict):
    """Only downscale if the video exceeds the preset. Never upscale."""
    if preset["long"] is None:
        return None
    w, h = info["width"], info["height"]
    portrait = h > w
    max_w, max_h = (preset["short"], preset["long"]) if portrait else (preset["long"], preset["short"])
    if w <= max_w and h <= max_h:
        return None
    return f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"


def optimize(path: Path, args) -> None:
    info = probe(path)
    preset = PRESETS[args.preset]

    fps = args.fps if args.fps else min(round(info["fps"]), preset["max_fps"])
    bitrate = args.bitrate if args.bitrate else preset["bitrate"]
    maxrate = round(bitrate * 1.5, 1)
    bufsize = bitrate * 2
    scale = build_scale_filter(info, preset)

    out = path.with_name(f"{path.stem}_tiktok.mp4")
    if out.exists() and not args.overwrite:
        print(f"Skipping {path.name}: {out.name} already exists (use --overwrite)")
        return

    print(f"\n=== {path.name} ===")
    print(f"Source : {info['width']}x{info['height']} @ {info['fps']:.2f}fps, "
          f"{info['codec']}, {info['size_mb']:.1f} MB, {info['duration']:.1f}s")
    print(f"Target : {'scaled, ' if scale else 'original size, '}{fps}fps, "
          f"{bitrate} Mbps {args.codec.upper()}")

    cmd = ["ffmpeg", "-y" if args.overwrite else "-n", "-hide_banner", "-i", str(path)]

    if args.codec == "hevc":
        cmd += ["-c:v", "libx265", "-tag:v", "hvc1", "-preset", args.speed]
    else:
        cmd += ["-c:v", "libx264", "-profile:v", "high", "-preset", args.speed]

    cmd += [
        "-b:v", f"{bitrate}M",
        "-maxrate", f"{maxrate}M",
        "-bufsize", f"{bufsize}M",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-fps_mode", "cfr",          # constant frame rate
    ]
    if scale:
        cmd += ["-vf", scale]

    cmd += [
        "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out),
    ]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"Failed: {path.name}")
        return

    new_mb = out.stat().st_size / (1024 * 1024)
    print(f"Done   : {out.name} ({new_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Optimize videos for TikTok upload.")
    parser.add_argument("files", nargs="+", help="Video file(s) to optimize")
    parser.add_argument("--preset", choices=PRESETS.keys(), default="1080p",
                        help="1080p (default), 4k, or source (keep original resolution)")
    parser.add_argument("--fps", type=int, help="Force output fps (default: keep source, capped by preset)")
    parser.add_argument("--bitrate", type=float, help="Video bitrate in Mbps (default depends on preset)")
    parser.add_argument("--codec", choices=["h264", "hevc"], default="h264",
                        help="h264 (default, most compatible) or hevc")
    parser.add_argument("--speed", default="slow",
                        choices=["ultrafast", "fast", "medium", "slow", "slower"],
                        help="Encoder preset: slower = better quality per MB (default: slow)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args()

    check_ffmpeg()

    for f in args.files:
        p = Path(f)
        if not p.is_file():
            print(f"Not found: {f}")
            continue
        optimize(p, args)

    print("\nAll done. Upload on TikTok web with 'Upload HD' on, visibility set to Everyone.")
    print("Don't edit the video in TikTok after uploading.")


if __name__ == "__main__":
    main()

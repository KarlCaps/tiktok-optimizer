#!/usr/bin/env python3
"""
TikTok Optimizer

retime (default for H.264 files): the video and audio are copied untouched (no
re-encoding, zero quality loss) and only their timestamps are stretched 2x.
Optional experimental layers, based on analysis of a similar tool's output:
  --decoy             add a second audio track padded with tiny filler samples
  --unknown-duration  set the movie header duration to "unknown"
  --full              both of the above

reencode: clean high-bitrate H.264/HEVC MP4 (used automatically for non-H.264).

Requires Python 3.8+ and FFmpeg (ffmpeg + ffprobe) in PATH.

    python tiktok_optimizer.py video.mp4                # layer 1 only
    python tiktok_optimizer.py video.mp4 --decoy        # layers 1 + 2
    python tiktok_optimizer.py video.mp4 --full         # layers 1 + 2 + 3
    python tiktok_optimizer.py video.mp4 --mode reencode --preset 1080p
"""

import argparse
import copy
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

PRESETS = {
    "1080p": {"long": 1920, "short": 1080, "bitrate": 15, "max_fps": 60},
    "4k":    {"long": 3840, "short": 2160, "bitrate": 40, "max_fps": 60},
    "source": {"long": None, "short": None, "bitrate": 25, "max_fps": 120},
}
FILLER = b"\x00\x00\x00\x04\x00\x00\x00\x00"  # 8-byte filler sample


# --------------------------------------------------------------------------
# Minimal MP4 box patcher (layers 2 and 3)
# --------------------------------------------------------------------------
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


class Box:
    def __init__(self, typ, payload=b"", children=None):
        self.typ, self.payload, self.children = typ, payload, children

    def find(self, *path):
        node = self
        for t in path:
            node = next((c for c in node.children if c.typ == t), None)
            if node is None:
                return None
        return node


def parse_boxes(data):
    out, off = [], 0
    while off + 8 <= len(data):
        size, typ = struct.unpack(">I4s", data[off:off + 8])
        hdr = 8
        if size == 1:
            size, hdr = struct.unpack(">Q", data[off + 8:off + 16])[0], 16
        elif size == 0:
            size = len(data) - off
        body = data[off + hdr:off + size]
        out.append(Box(typ, children=parse_boxes(body)) if typ in CONTAINERS else Box(typ, bytes(body)))
        off += size
    return out


def build_box(b):
    body = b"".join(build_box(c) for c in b.children) if b.children is not None else b.payload
    return struct.pack(">I4s", len(body) + 8, b.typ) + body


def shift_offsets(moov, delta):
    for trak in (c for c in moov.children if c.typ == b"trak"):
        stco = trak.find(b"mdia", b"minf", b"stbl", b"stco")
        if stco is None:
            raise RuntimeError("64-bit chunk offsets (co64) are not supported")
        n = struct.unpack(">I", stco.payload[4:8])[0]
        offs = struct.unpack(">%dI" % n, stco.payload[8:8 + 4 * n])
        stco.payload = stco.payload[:8] + struct.pack(">%dI" % n, *[o + delta for o in offs])


def add_decoy(moov, filler_off):
    """Duplicate the first audio track and append 9x its sample count in filler samples."""
    traks = [c for c in moov.children if c.typ == b"trak"]
    src = next((t for t in traks if t.find(b"mdia", b"hdlr").payload[8:12] == b"soun"), None)
    if src is None:
        print("  (no audio track, decoy skipped)")
        return
    new = copy.deepcopy(src)
    new.children = [c for c in new.children if c.typ != b"edts"]

    def tid_pos(tkhd):
        return 20 if tkhd.payload[0] == 1 else 12

    ids = [struct.unpack(">I", t.find(b"tkhd").payload[tid_pos(t.find(b"tkhd")):][:4])[0] for t in traks]
    tk = new.find(b"tkhd")
    p = tid_pos(tk)
    tk.payload = tk.payload[:p] + struct.pack(">I", max(ids) + 1) + tk.payload[p + 4:]

    stbl = new.find(b"mdia", b"minf", b"stbl")
    stts, stsz, stsc, stco = (stbl.find(t) for t in (b"stts", b"stsz", b"stsc", b"stco"))
    ssize, count = struct.unpack(">II", stsz.payload[4:12])
    table = stsz.payload[12:12 + 4 * count] if ssize == 0 else struct.pack(">I", ssize) * count
    n_fill = 9 * count
    stsz.payload = stsz.payload[:4] + struct.pack(">II", 0, count + n_fill) + table + struct.pack(">I", 8) * n_fill
    n = struct.unpack(">I", stts.payload[4:8])[0]
    stts.payload = stts.payload[:4] + struct.pack(">I", n + 1) + stts.payload[8:] + struct.pack(">II", n_fill, 1)
    chunks = struct.unpack(">I", stco.payload[4:8])[0]
    n = struct.unpack(">I", stsc.payload[4:8])[0]
    stsc.payload = stsc.payload[:4] + struct.pack(">I", n + 1) + stsc.payload[8:] + struct.pack(">III", chunks + 1, n_fill, 1)
    stco.payload = stco.payload[:4] + struct.pack(">I", chunks + 1) + stco.payload[8:] + struct.pack(">I", filler_off)

    last = max(i for i, c in enumerate(moov.children) if c.typ == b"trak")
    moov.children.insert(last + 1, new)
    mvhd = moov.find(b"mvhd")
    mvhd.payload = mvhd.payload[:-4] + struct.pack(">I", max(ids) + 2)
    return n_fill


def set_unknown_duration(moov):
    mvhd = moov.find(b"mvhd")
    pl = mvhd.payload
    if pl[0] == 1:
        ts = struct.unpack(">I", pl[20:24])[0]
        rest = pl[32:]
    else:
        ts = struct.unpack(">I", pl[12:16])[0]
        rest = pl[20:]
    mvhd.payload = b"\x01\x00\x00\x00" + bytes(16) + struct.pack(">I", ts) + b"\xff" * 8 + rest


def patch_mp4(src, dst, decoy, unknown_duration):
    size_total = os.path.getsize(src)
    tops, off = [], 0
    with open(src, "rb") as f:
        while off < size_total:
            f.seek(off)
            h = f.read(16)
            size, typ = struct.unpack(">I4s", h[:8])
            hdr = 8
            if size == 1:
                size, hdr = struct.unpack(">Q", h[8:16])[0], 16
            elif size == 0:
                size = size_total - off
            tops.append((typ, off, size, hdr))
            off += size
        mdats = [t for t in tops if t[0] == b"mdat"]
        moovs = [t for t in tops if t[0] == b"moov"]
        if len(mdats) != 1 or len(moovs) != 1:
            raise RuntimeError("unsupported MP4 layout")
        _, m_off, m_size, m_hdr = mdats[0]
        f.seek(moovs[0][1] + moovs[0][3])
        moov = Box(b"moov", children=parse_boxes(f.read(moovs[0][2] - moovs[0][3])))

        extra = b""
        if decoy:
            count = struct.unpack(">I", next(t for t in moov.children if t.typ == b"trak"
                                             and t.find(b"mdia", b"hdlr").payload[8:12] == b"soun")
                                  .find(b"mdia", b"minf", b"stbl", b"stsz").payload[8:12])[0]
            extra = FILLER * (9 * count)
            add_decoy(moov, m_off + m_size)  # old coordinates
        if unknown_duration:
            set_unknown_duration(moov)

        old_moov_len = moovs[0][2]
        new_moov_len = len(build_box(moov))
        delta = (new_moov_len - old_moov_len) if moovs[0][1] < m_off else 0
        shift_offsets(moov, delta)
        new_moov = build_box(moov)

        new_m_size = m_size + len(extra)
        with open(dst, "wb") as out:
            for typ, o, size, hdr in tops:
                if typ == b"moov":
                    out.write(new_moov)
                elif typ == b"mdat":
                    if hdr == 16:
                        out.write(struct.pack(">I4sQ", 1, b"mdat", new_m_size))
                    else:
                        out.write(struct.pack(">I4s", new_m_size, b"mdat"))
                    f.seek(o + hdr)
                    left = size - hdr
                    while left:
                        chunk = f.read(min(left, 8 << 20))
                        out.write(chunk)
                        left -= len(chunk)
                    out.write(extra)
                else:
                    f.seek(o)
                    out.write(f.read(size))


# --------------------------------------------------------------------------
# ffmpeg helpers
# --------------------------------------------------------------------------
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
        "codec": v.get("codec_name", "?"), "pix_fmt": v.get("pix_fmt", "?"),
        "width": int(v["width"]), "height": int(v["height"]),
        "fps": float(num) / float(den) if float(den) else 30.0,
        "audio_tracks": sum(1 for s in streams if s.get("codec_type") == "audio"),
        "duration": float(data["format"].get("duration", 0)),
        "size_mb": int(data["format"].get("size", 0)) / (1024 * 1024),
    }


def fmt_time(s: float) -> str:
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


def build_scale_filter(info, preset):
    if preset["long"] is None:
        return None
    w, h = info["width"], info["height"]
    mw, mh = (preset["short"], preset["long"]) if h > w else (preset["long"], preset["short"])
    if w <= mw and h <= mh:
        return None
    return f"scale={mw}:{mh}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"


def retime_cmd(path, out, info, args):
    tag = "hvc1" if info["codec"] in ("hevc", "h265") else "avc1"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-itsscale:v", str(args.stretch), "-itsscale:a", str(args.stretch),
           "-i", str(path), "-map", "0:v:0", "-c:v", "copy", "-tag:v", tag]
    if args.audio == "keep" and info["audio_tracks"]:
        cmd += ["-map", "0:a:0", "-c:a", "copy"]
    else:
        cmd += ["-an"]
    return cmd + ["-movflags", "+faststart", str(out)]


def reencode_cmd(path, out, info, args):
    preset = PRESETS[args.preset]
    fps = args.fps if args.fps else min(round(info["fps"]), preset["max_fps"])
    br = args.bitrate if args.bitrate else preset["bitrate"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(path)]
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
    decoy = args.decoy or args.full
    unk = args.unknown_duration or args.full
    suffix = "_full" if (decoy and unk) else "_decoy" if decoy else "_unkdur" if unk else ""

    mode = args.mode
    if mode == "auto":
        ok = info["codec"] == "h264" and info["pix_fmt"] == "yuv420p"
        mode = "retime" if ok else "reencode"
        if not ok:
            print(f"Note: {info['codec']}/{info['pix_fmt']} source, so re-encoding to H.264.")
    out = path.with_name(f"{path.stem}_tiktok{suffix if mode == 'retime' else ''}.mp4")
    if out.exists() and not args.overwrite:
        print(f"Skipping {path.name}: {out.name} already exists (use --overwrite)")
        return

    print(f"\n=== {path.name} ===")
    print(f"Source : {info['width']}x{info['height']} @ {info['fps']:.2f}fps, {info['codec']}, "
          f"{info['size_mb']:.1f} MB, {fmt_time(info['duration'])}")

    if mode == "retime":
        layers = "1" + (" + 2 (decoy track)" if decoy else "") + (" + 3 (unknown duration)" if unk else "")
        print(f"Mode   : retime {args.stretch:g}x, copy only, layers {layers}")
        tmp = out.with_name(out.stem + ".tmp.mp4") if (decoy or unk) else out
        if subprocess.run(retime_cmd(path, tmp, info, args)).returncode != 0:
            print(f"Failed: {path.name}")
            return
        if tmp != out:
            try:
                patch_mp4(tmp, out, decoy, unk)
            finally:
                tmp.unlink(missing_ok=True)
    else:
        cmd, fps, br = reencode_cmd(path, out, info, args)
        print(f"Mode   : re-encode, {fps}fps, {br} Mbps {args.codec.upper()}")
        if subprocess.run(cmd).returncode != 0:
            print(f"Failed: {path.name}")
            return

    o = probe(out)
    print(f"Done   : {out.name}  {o['width']}x{o['height']} @ {o['fps']:.0f}fps, "
          f"{fmt_time(o['duration'])}, {o['size_mb']:.1f} MB, {o['audio_tracks']} audio track(s)")


def main():
    p = argparse.ArgumentParser(description="Optimize videos for TikTok upload.")
    p.add_argument("files", nargs="+", help="Video file(s)")
    p.add_argument("--mode", choices=["auto", "retime", "reencode"], default="auto")
    p.add_argument("--stretch", type=float, default=2.0, help="retime: timestamp multiplier (default 2)")
    p.add_argument("--audio", choices=["keep", "drop"], default="keep", help="retime: keep or drop audio")
    p.add_argument("--decoy", action="store_true", help="retime layer 2: second audio track with filler samples")
    p.add_argument("--unknown-duration", action="store_true", help="retime layer 3: movie header duration unknown")
    p.add_argument("--full", action="store_true", help="retime layers 2 + 3")
    p.add_argument("--preset", choices=PRESETS.keys(), default="1080p", help="reencode: resolution limit")
    p.add_argument("--fps", type=int, help="reencode: force fps")
    p.add_argument("--bitrate", type=float, help="reencode: video bitrate in Mbps")
    p.add_argument("--codec", choices=["h264", "hevc"], default="h264", help="reencode: output codec")
    p.add_argument("--speed", default="slow", choices=["ultrafast", "fast", "medium", "slow", "slower"])
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

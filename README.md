# TikTok Optimizer

A small command-line tool that re-encodes your videos into a clean, high-bitrate H.264 (or HEVC) MP4, giving TikTok the best possible source file to work with.

It runs **locally on your computer**. No accounts, no uploads to third-party servers.

## Try it in your browser

**https://karlcaps.github.io/tiktok-optimizer/** (no install; runs locally in your browser)

## Two modes

- **Retime (default for H.264 files):** copies your video stream untouched and only rewrites its timestamps (2x length, half the frame rate label). No re-encoding, so there is zero quality loss and it finishes in seconds. Audio is also copied, with its timestamps stretched the same way (or removed with `--audio drop`). Two optional experimental layers, based on analysing a similar tool's output, can be added with `--decoy` (second audio track padded with filler samples), `--unknown-duration` (movie header duration set to unknown), or `--full` for both.
- **Re-encode:** a clean high-bitrate H.264/HEVC MP4, used automatically for non-H.264 sources (such as HEVC) or with `--mode reencode`.

> **Experimental:** retime mode is based on analysing how a similar service changes files. Post a short test first to confirm TikTok handles it the way you expect. TikTok re-encodes every upload either way.

## Requirements

- Python 3.8+
- [FFmpeg](https://ffmpeg.org/download.html) (`ffmpeg` and `ffprobe` must be in your PATH)

No Python packages need to be installed.

## Install

```bash
git clone https://github.com/KarlCaps/tiktok-optimizer.git
cd tiktok-optimizer
```

## Usage

```bash
python tiktok_optimizer.py video.mp4
python tiktok_optimizer.py video.mp4 --audio drop
python tiktok_optimizer.py video.mp4 --mode reencode --preset 4k
python tiktok_optimizer.py clip1.mp4 clip2.mov --fps 60 --bitrate 20
python tiktok_optimizer.py video.mov --codec hevc
```

Output is saved next to the original as `<name>_tiktok.mp4`.

**Windows:** drag and drop a video onto `optimize.bat` (1080p preset).

### Options

| Option | Description |
| --- | --- |
| `--mode` | `auto` (default), `retime`, or `reencode` |
| `--stretch` | Retime: length multiplier (default 2) |
| `--audio` | Retime: `keep` (default) or `drop` |
| `--decoy` / `--unknown-duration` / `--full` | Retime: experimental layers 2 and 3 |
| `--preset` | `1080p` (default), `4k`, or `source` (keep original resolution) |
| `--fps` | Force output fps (default: keep source, capped at 60 for 1080p/4k) |
| `--bitrate` | Video bitrate in Mbps (default: 15 for 1080p, 40 for 4k, 25 for source) |
| `--codec` | `h264` (default, most compatible) or `hevc` |
| `--speed` | `ultrafast`, `fast`, `medium`, `slow` (default), `slower` |
| `--overwrite` | Overwrite existing output files |

## Uploading to TikTok

1. Use **TikTok web** (desktop) and turn on **Upload HD**
2. Set visibility to **Everyone**
3. Don't edit the video in TikTok after uploading (sounds, filters and trimming trigger re-encoding)
4. On iOS, upload from the Files app rather than the photo gallery to preserve frame rate

## Contributing

Issues and pull requests are welcome.

## License

MIT. See [LICENSE](LICENSE).

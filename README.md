# TikTok Optimizer

A small command-line tool that re-encodes your videos into a clean, high-bitrate H.264 (or HEVC) MP4, giving TikTok the best possible source file to work with.

It runs **locally on your computer**. No accounts, no uploads to third-party servers.

## What it does

- Reads your video's resolution, frame rate and codec with `ffprobe`
- Downscales only if the video exceeds the chosen preset (never upscales)
- Keeps your frame rate, with a constant frame rate output
- Encodes at a high bitrate with `yuv420p`, `faststart` and 320k AAC audio
- Supports portrait and landscape videos and batch processing

> **Note:** TikTok re-encodes every upload. This tool does not bypass that. It gives TikTok a high-quality source so the final result looks as good as possible.

## Requirements

- Python 3.8+
- [FFmpeg](https://ffmpeg.org/download.html) (`ffmpeg` and `ffprobe` must be in your PATH)

No Python packages need to be installed.

## Install

```bash
git clone https://github.com/YOUR_USERNAME/tiktok-optimizer.git
cd tiktok-optimizer
```

## Usage

```bash
python tiktok_optimizer.py video.mp4
python tiktok_optimizer.py video.mp4 --preset 4k
python tiktok_optimizer.py clip1.mp4 clip2.mov --fps 60 --bitrate 20
python tiktok_optimizer.py video.mov --codec hevc
```

Output is saved next to the original as `<name>_tiktok.mp4`.

**Windows:** drag and drop a video onto `optimize.bat` (1080p preset).

### Options

| Option | Description |
| --- | --- |
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

#!/usr/bin/env bash
# Rebuild the whole video from video/audio/*.wav (guide track or your own voice after prep_voice.py).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --with playwright python video/render_scenes.py --jobs 4 --split 3
uv run --with pillow python video/assemble.py
echo "Done: video/arvo.mp4"

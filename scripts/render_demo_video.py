#!/usr/bin/env python3
"""Compose phone footage beside a deterministic recording of the actual frontend.

Run Vite first. Dependencies: frontend npm install; Playwright Chromium;
uv run --with imageio-ffmpeg python scripts/render_demo_video.py SOURCE.MOV
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import imageio_ffmpeg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path('demo/generated/breacheye-side-by-side.mp4'))
    parser.add_argument('--reuse-frames', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = output.parent / 'frontend-frames'
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run([ffmpeg, '-i', str(source)], capture_output=True, text=True)
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', probe.stderr)
    if not match:
        raise SystemExit('Could not determine source video duration')
    h, m, s = map(float, match.groups())
    duration = h * 3600 + m * 60 + s
    if not args.reuse_frames:
        subprocess.run(['node', str(root / 'frontend/scripts/capture-demo.mjs'), str(frames), str(duration)], cwd=root, check=True)
    font = os.environ.get('DEMO_FONT', '/System/Library/Fonts/Supplemental/Arial.ttf')
    def text(label, x, y, size, color):
        return f"drawtext=fontfile='{font}':text='{label}':x={x}:y={y}:fontsize={size}:fontcolor={color}"
    filters = (
        '[0:v]setpts=PTS-STARTPTS,scale=624:832:force_original_aspect_ratio=decrease,setsar=1[left];'
        '[1:v]scale=1248:878,setsar=1[right];'
        f'color=c=0x090f18:s=1920x990:r=30:d={duration}[base];'
        '[base][left]overlay=x=16:y=124[a];[a][right]overlay=x=656:y=100[b];[b]'
        + ','.join([
            text('BREACHEYE', 22, 22, 30, '0x85d8cf'),
            text('INDOOR FLIGHT / FRONTEND DEMO', 275, 28, 19, '0xe2e8f0'),
            text('01  /  RECORDED TELLO FLIGHT', 22, 76, 17, '0x9aaabd'),
            text('02  /  FRONTEND SIMULATION', 670, 76, 17, '0x9aaabd'),
        ]) + '[out]'
    )
    temporary = output.with_name(output.stem + '.tmp.mp4')
    subprocess.run([ffmpeg, '-y', '-loglevel', 'warning', '-i', str(source),
        '-framerate', '30', '-i', str(frames / '%05d.png'), '-filter_complex', filters,
        '-map', '[out]', '-map', '0:a?', '-t', str(duration), '-r', '30',
        '-c:v', 'libx264', '-crf', '19', '-preset', 'medium', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '160k', '-map_metadata', '-1', '-movflags', '+faststart', str(temporary)], check=True)
    temporary.replace(output)
    print(output)


if __name__ == '__main__':
    main()

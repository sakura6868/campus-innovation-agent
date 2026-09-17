"""阶段二：把 ASS 字幕烧入 webm，输出 mp4（无音轨）。

关键点：以 cwd=REC_DIR 运行 ffmpeg，subtitles 滤镜只写文件名（无盘符冒号），
规避 ffmpeg 在 Windows 下把 "D:" 当选项分隔符导致解析失败/卡死的坑。

用法：python burn_subs.py [--in demo_rec.webm] [--ass demo_subtitles.ass]
                        [--out ../campus-agent-demo-final.mp4] [--trim 6]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REC_DIR = ROOT / "demo" / "_rec"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="demo_rec.webm")
    ap.add_argument("--ass", dest="ass", default="demo_subtitles.ass")
    ap.add_argument("--out", dest="out", default=str(ROOT / "demo" / "campus-agent-demo-final.mp4"))
    ap.add_argument("--trim", type=float, default=0.0, help="只处理前 N 秒（自检用）")
    args = ap.parse_args()

    ffmpeg = subprocess.check_output(
        [str(ROOT / "venv" / "Scripts" / "python.exe"),
         "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"]
    ).decode().strip()

    cmd = [ffmpeg, "-y", "-i", args.src,
           "-vf", f"subtitles={Path(args.ass).name}",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
           "-movflags", "+faststart"]
    if args.trim > 0:
        cmd += ["-t", str(args.trim)]
    cmd += [args.out]
    print("CWD:", REC_DIR)
    print("CMD:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(REC_DIR))
    print("DONE:", args.out, Path(args.out).stat().st_size, flush=True)


if __name__ == "__main__":
    main()

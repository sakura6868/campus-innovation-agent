"""将项目页面截图和中文旁白合成为 3—5 分钟演示视频。

示例：
  FFMPEG_BIN=/path/to/ffmpeg python scripts/build_demo_video.py \
    --shots-dir /tmp/campus-agent-video-shots --output demo/campus-agent-demo-final.mp4

脚本只读取页面截图、旁白稿和本机语音服务；不会访问用户账户、密钥或运行数据库。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIDEO_SIZE = (1920, 1080)
SCENES = (
    ("01-login.png", "安全登录与演示账号", "虚构学生画像 · 无管理员权限", 20),
    ("02-home.png", "首页：把赛事信息转为今日行动", "焦点、匹配、官方变化与项目进度一屏呈现", 22),
    ("03-hall-search.png", "赛事大厅：正式名称精准检索", "146 条可追溯赛事 · 类别 / 年份 / 报名状态筛选", 22),
    ("04-detail.png", "赛事详情：事实与来源同时呈现", "资格、队伍、节点、材料与官网证据可核验", 20),
    ("05-recommend.png", "解释型推荐：先门控，后评分", "匹配理由、能力缺口与取舍建议清晰可读", 22),
    ("06-portfolio.png", "行动路线：三种可执行机会组合", "稳妥 / 均衡 / 冲刺 · 周容量与截止冲突共同约束", 22),
    ("07-project-timeline.png", "项目时间线：官方节点与执行任务对齐", "七阶段闭环 · 材料、任务和截止时间同步推进", 21),
    ("08-project-board.png", "项目看板：阻止跳过前置事项", "任务依赖、状态推进与材料管理形成工作闭环", 21),
    ("09-radar.png", "机会提醒：监控变化但不自动改写事实", "差异进入人工复核 · 异常来源保留真实状态", 21),
    ("10-agent-answer.png", "可信智能顾问：给出选择，也说明理由", "三场赛事、匹配度、能力缺口、取舍与回答依据", 24),
)


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size, index=0)
    return ImageFont.load_default()


def fit_on_canvas(image: Image.Image) -> Image.Image:
    """完整保留浏览器画面；16:9 输出的两侧使用同主题柔化背景补齐。"""
    source = image.convert("RGB")
    # 背景允许裁切但会被模糊处理；前景始终按 contain 规则完整保留。
    cover_scale = max(VIDEO_SIZE[0] / source.width, VIDEO_SIZE[1] / source.height)
    cover_image = source.resize(
        (round(source.width * cover_scale), round(source.height * cover_scale)), Image.Resampling.LANCZOS
    )
    cover_left = (cover_image.width - VIDEO_SIZE[0]) // 2
    cover_top = (cover_image.height - VIDEO_SIZE[1]) // 2
    background = cover_image.crop((cover_left, cover_top, cover_left + VIDEO_SIZE[0], cover_top + VIDEO_SIZE[1]))
    background = background.filter(ImageFilter.GaussianBlur(26))
    background = Image.blend(background, Image.new("RGB", VIDEO_SIZE, (20, 23, 30)), 0.58)

    scale = min(VIDEO_SIZE[0] / source.width, VIDEO_SIZE[1] / source.height)
    foreground = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
    position = ((VIDEO_SIZE[0] - foreground.width) // 2, (VIDEO_SIZE[1] - foreground.height) // 2)
    background.paste(foreground, position)
    return background


def make_labeled_frame(source: Path, title: str, subtitle: str, output: Path) -> None:
    canvas = fit_on_canvas(Image.open(source))
    overlay = Image.new("RGBA", VIDEO_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((72, 830, 1848, 1024), radius=28, fill=(21, 24, 31, 226), outline=(220, 179, 109, 100), width=2)
    draw.text((112, 870), title, font=find_font(42, True), fill=(244, 231, 207, 255))
    draw.text((114, 934), subtitle, font=find_font(26), fill=(205, 199, 205, 255))
    draw.text((1690, 72), "校园科创导航智能体", font=find_font(22), fill=(239, 199, 125, 230))
    composited = canvas.convert("RGBA")
    composited.alpha_composite(overlay)
    composited.convert("RGB").save(output, quality=95)


def make_card(title: str, subtitle: str, detail: str, output: Path) -> None:
    canvas = Image.new("RGB", VIDEO_SIZE, (26, 29, 36))
    draw = ImageDraw.Draw(canvas)
    for index in range(12):
        alpha = 18 + index * 4
        draw.ellipse((1350 - index * 64, 50 + index * 32, 2060 + index * 25, 760 + index * 35), fill=(70 + alpha, 57 + alpha // 2, 61 + alpha // 3))
    draw.rounded_rectangle((150, 180, 1770, 900), radius=42, fill=(34, 38, 48), outline=(216, 179, 109), width=3)
    draw.text((245, 310), "CAMPUS INNOVATION AGENT", font=find_font(28), fill=(216, 179, 109))
    draw.text((245, 410), title, font=find_font(68, True), fill=(243, 232, 216))
    draw.text((245, 535), subtitle, font=find_font(34), fill=(199, 191, 201))
    draw.rounded_rectangle((245, 660, 1675, 775), radius=20, fill=(26, 29, 36))
    draw.text((285, 700), detail, font=find_font(28), fill=(234, 211, 163))
    canvas.save(output, quality=95)


def duration_of_audio(ffmpeg: str, audio: Path) -> float:
    result = subprocess.run([ffmpeg, "-i", str(audio)], capture_output=True, text=True, check=False)
    text = result.stderr
    marker = "Duration: "
    if marker not in text:
        return 0.0
    value = text.split(marker, 1)[1].split(",", 1)[0].strip()
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成校园科创导航智能体正式演示视频")
    parser.add_argument("--shots-dir", type=Path, required=True, help="浏览器截图目录")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "demo" / "campus-agent-demo-final.mp4")
    parser.add_argument("--narration", type=Path, default=PROJECT_ROOT / "demo" / "正式演示旁白稿.txt")
    parser.add_argument("--voice", default="Tingting", help="macOS say 中文语音")
    parser.add_argument("--rate", type=int, default=170, help="旁白语速")
    parser.add_argument("--ffmpeg", default=os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg"), help="ffmpeg 可执行文件路径")
    args = parser.parse_args()
    if not args.ffmpeg:
        raise SystemExit("未找到 ffmpeg；请通过 --ffmpeg 或 FFMPEG_BIN 指定路径。")
    missing = [name for name, *_ in SCENES if not (args.shots_dir / name).is_file()]
    if missing:
        raise SystemExit("缺少截图：" + ", ".join(missing))
    if not args.narration.is_file():
        raise SystemExit(f"旁白稿不存在：{args.narration}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="campus-agent-video-") as directory:
        work = Path(directory)
        title_path = work / "00-title.jpg"
        closing_path = work / "99-closing.jpg"
        make_card("校园科创导航智能体", "从赛事信息到可执行参赛计划", "可信来源 · 个性化匹配 · 项目闭环 · 可解释 AI", title_path)
        make_card("工程验收与安全边界", "15 / 15 正式评测 · 59 / 59 自动回归通过", "离线可运行 · 来源变化人工审核 · 最小化采集与权限隔离", closing_path)

        entries: list[tuple[Path, int]] = [(title_path, 22)]
        for index, (name, title, subtitle, seconds) in enumerate(SCENES, start=1):
            frame = work / f"{index:02d}-frame.jpg"
            make_labeled_frame(args.shots_dir / name, title, subtitle, frame)
            entries.append((frame, seconds))
        entries.append((closing_path, 28))

        audio = work / "narration.aiff"
        subprocess.run(["say", "-v", args.voice, "-r", str(args.rate), "-f", str(args.narration), "-o", str(audio)], check=True)
        target_duration = sum(seconds for _, seconds in entries)
        concat_file = work / "slides.txt"
        lines: list[str] = []
        for frame, seconds in entries:
            lines.append(f"file '{frame.as_posix()}'")
            lines.append(f"duration {seconds}")
        lines.append(f"file '{entries[-1][0].as_posix()}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        command = [
            args.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-i", str(audio),
            "-filter_complex", "[0:v]fps=30,format=yuv420p[v];[1:a]apad[a]",
            "-map", "[v]", "-map", "[a]", "-t", str(target_duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "160k",
            str(args.output),
        ]
        subprocess.run(command, check=True)
        spoken = duration_of_audio(args.ffmpeg, audio)
        print(f"video: {args.output}")
        print(f"duration target: {target_duration}s; narration: {spoken:.2f}s")


if __name__ == "__main__":
    main()

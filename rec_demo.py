"""录制最新 UI 演示并转 mp4（覆盖：强制登录 -> 画像推荐分化 -> 千问问答 -> 联网卡片 -> 赛事大厅）。

依赖：playwright（已装）+ chromium（已下载）。录屏用 Chromium 原生 webm，
再用 imageio_ffmpeg 自带 ffmpeg 转成校内平台可直接打开的 mp4。
"""
import os
import glob
import subprocess
from playwright.sync_api import sync_playwright

# 转码用的 ffmpeg 来自项目 3.8 venv 的 imageio_ffmpeg（3.13 venv 装不上该包）
FF_PY = r"D:/NJUSTAGENT/campus-innovation-agent/venv/Scripts/python.exe"

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8011"
REC_DIR = os.path.join(ROOT, "demo", "_rec")
MP4 = os.path.join(ROOT, "demo", "campus-agent-demo.mp4")
WIDTH, HEIGHT = 1280, 800


def step(page, fn, label):
    try:
        fn()
        print("OK  :", label)
    except Exception as e:  # noqa: BLE001
        print("FAIL:", label, "->", repr(e))


def main():
    os.makedirs(REC_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=REC_DIR,
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(900)

        # 1) 强制登录页（每次进入都弹，已可见）
        step(page, lambda: (
            page.wait_for_selector("#login-overlay:not(.hidden)", timeout=8000),
            page.fill("#login-username", "test"),
            page.fill("#login-password", "test123"),
            page.click("#login-form button[type=submit]"),
        ), "login as test")
        page.wait_for_timeout(1600)

        # 2) 我的推荐（默认画像）
        step(page, lambda: (
            page.click("a[data-nav=recommend]"),
            page.wait_for_selector("#recommend-list .card", timeout=9000),
        ), "recommend view (default)")
        page.wait_for_timeout(2800)

        # 3) 画像页 + 切换学生类型
        step(page, lambda: (
            page.click("a[data-nav=profile]"),
            page.wait_for_selector("#test-switch-panel:not(.hidden)", timeout=8000),
        ), "profile view + test switch panel")
        page.wait_for_timeout(1300)
        step(page, lambda: page.click("a[data-nav=profile]"), "ensure profile")
        page.wait_for_selector("#test-types button", timeout=8000)
        type_loc = page.locator("#test-types button")
        n = type_loc.count()
        print("TEST_TYPES_COUNT:", n)
        if n >= 1:
            type_loc.nth(0).click()
            page.wait_for_timeout(1000)
            step(page, lambda: page.click("a[data-nav=recommend]"), "recommend after type A")
            page.wait_for_timeout(2800)
            step(page, lambda: page.click("a[data-nav=profile]"), "back to profile")
            page.wait_for_timeout(800)
        if n >= 2:
            type_loc.nth(1).click()
            page.wait_for_timeout(1000)
            step(page, lambda: page.click("a[data-nav=recommend]"), "recommend after type B (分化)")
            page.wait_for_timeout(2800)

        # 4) 智能问答：本地证据 + 千问润色（带 [n] 引用）
        step(page, lambda: (
            page.click("a[data-nav=agent]"),
            page.wait_for_selector("#agent-q", timeout=8000),
        ), "agent view")
        page.fill("#agent-q", "2026 高教社杯数学建模的报名截止是什么时候？")
        page.click("#agent-send")
        page.wait_for_timeout(7000)

        # 5) 联网搜索补充层（🌐 卡片）
        page.fill("#agent-q", "2026 蓝桥杯报名通知 帮我联网查最新动态")
        page.click("#agent-send")
        try:
            page.wait_for_selector(".web-results", timeout=20000)
            print("OK  : web-results card appeared")
        except Exception as e:  # noqa: BLE001
            print("FAIL: web-results card ->", repr(e))
        page.wait_for_timeout(4500)

        # 6) 赛事大厅（可信 not_found 红字可见）
        step(page, lambda: (
            page.click("a[data-nav=hall]"),
            page.wait_for_selector("#hall-list .card", timeout=9000),
        ), "hall view")
        page.wait_for_timeout(3000)

        ctx.close()
        browser.close()

    # 转码 webm -> mp4
    webms = glob.glob(os.path.join(REC_DIR, "*.webm"))
    if not webms:
        print("NO_WEBM_FOUND")
        return
    webm = max(webms, key=os.path.getmtime)
    print("WEBM:", webm)
    exe = subprocess.check_output(
        [FF_PY, "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"]
    ).decode().strip()
    cmd = [
        exe, "-y", "-i", webm,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", MP4,
    ]
    subprocess.run(cmd, check=True)
    print("MP4_DONE:", MP4, "size=", os.path.getsize(MP4))


if __name__ == "__main__":
    main()

"""重录校园科创导航智能体演示视频（无配音，仅烧入自然中文字幕）。

阶段一（本脚本）：playwright 实时录屏（静音）-> 立即保存 webm + 写出字幕时间轴(ASS/JSON)。
为避免 playwright 关闭浏览器在 Windows 上偶发卡死，保存视频后强制 os._exit(0)。
阶段二（burn_subs.py）：webm + ASS -> 烧入字幕的 mp4。

依赖：项目 venv 的 playwright + imageio_ffmpeg。
用法：先启动后端（uvicorn api:app --port 8012），再 python rec_demo2.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
BASE = os.environ.get("DEMO_BASE", "http://127.0.0.1:8012")
REC_DIR = ROOT / "demo" / "_rec"
WEBM = REC_DIR / "demo_rec.webm"
ASS = REC_DIR / "demo_subtitles.ass"
TIMINGS = REC_DIR / "demo_timings.json"
WIDTH, HEIGHT = 1440, 900

# —— 场景定义：kind=动作类型；dwell=字幕停留毫秒（也是该屏阅读时长）；lines=自然字幕（逐句）——
SCENES = [
    {"key": "login", "kind": "login",
     "lines": ["先登录演示账号。", "每次打开都会强制登录一次，这是为了保证数据安全。"]},
    {"key": "home", "kind": "route", "route": "#/home", "dwell": 11000,
     "lines": ["登录后看到的是为你定制的参赛首页。",
               "系统已经按你的身份，把最匹配的赛事排到了最前面。"]},
    {"key": "home_scroll", "kind": "scroll", "px": 520, "dwell": 7000,
     "lines": ["往下看，今天的官方变化和重点机会也都在这儿。",
               "想看什么，一屏就能接着点进去。"]},
    {"key": "recommend", "kind": "route", "route": "#/recommend", "dwell": 11000,
     "lines": ["这是匹配建议。",
               "每条都写了推荐理由、你的能力缺口，还有要不要冲的建议。"]},
    {"key": "profile", "kind": "route", "route": "#/profile", "dwell": 4500,
     "lines": ["我换个学生类型，看看推荐会不会跟着变。"]},
    {"key": "switch_a", "kind": "click_test_type", "idx": 1, "dwell": 2600,
     "lines": ["（切换成「算法卷王」画像）"]},
    {"key": "recommend_a", "kind": "route", "route": "#/recommend", "dwell": 9500,
     "lines": ["换成算法竞赛型之后，推荐里基本都是个人赛和算法类赛事。",
               "匹配度是按你的画像实时算出来的。"]},
    {"key": "switch_b", "kind": "click_test_type", "idx": 2, "dwell": 2600,
     "lines": ["（再换成「建模选手」画像）"]},
    {"key": "recommend_b", "kind": "route", "route": "#/recommend", "dwell": 9000,
     "lines": ["换成建模型，列表立刻转向三人队和论文类比赛。",
               "同一批赛事，推荐结果完全不同——这就是千人千面。"]},
    {"key": "detail", "kind": "open_detail", "dwell": 12000,
     "lines": ["点开一场比赛，事实和来源是一起给的。",
               "资格、队伍、时间节点，都能核对到官网。"]},
    {"key": "detail_scroll", "kind": "scroll", "px": 480, "dwell": 7000,
     "lines": ["往下翻，官方依据也附在后面，方便你当场核验。"]},
    {"key": "agent_ask", "kind": "agent_ask",
     "q": "2026 高教社杯数学建模的报名截止是什么时候？", "dwell": 14000,
     "lines": ["有具体问题，直接问智能顾问。",
               "它不光给答案，还把官方依据标成引用。",
               "比如这条比赛的报名截止时间，一眼就能看到。"]},
    {"key": "agent_web", "kind": "agent_ask",
     "q": "2026 蓝桥杯报名通知 帮我联网查最新动态", "dwell": 10000,
     "lines": ["想要最新动态，它会联网查官方通知。", "把来源卡片也附上，方便你点开核对。"]},
    {"key": "hall", "kind": "hall_search", "q": "蓝桥杯", "dwell": 8000,
     "lines": ["赛事大厅里能精准搜。",
               "注意这条标了红字——来源待核实，我们绝不替你编。"]},
    {"key": "radar", "kind": "route", "route": "#/radar", "dwell": 8500,
     "lines": ["机会提醒会盯着官方来源的变化。",
               "一旦有更新就推给你，但不会偷偷改掉事实。"]},
    {"key": "portfolio", "kind": "route", "route": "#/portfolio", "dwell": 9500,
     "lines": ["行动路线按你的容量和截止时间，", "给出稳妥、均衡、冲刺三种参赛组合。"]},
    {"key": "projects", "kind": "route", "route": "#/projects", "dwell": 8000,
     "lines": ["我的项目用几个视图管全过程。", "从关注、组队到进度，形成闭环。"]},
    {"key": "projects_scroll", "kind": "scroll", "px": 500, "dwell": 5000,
     "lines": ["看板视图能拦住你跳过前置任务，保证推进有秩序。"]},
    {"key": "admin_pipeline", "kind": "admin", "dwell": 8000,
     "lines": ["这是数据维护后台。",
               "十二个官方来源的变化会被自动捕获，进入人工复核。"]},
    {"key": "quality", "kind": "admin_quality", "dwell": 11000,
     "lines": ["这是质量驾驶舱，整页已经统一成深色主题。",
               "六个维度实时显示数据可信度。",
               "来源核验率、资料可用率，一目了然。"]},
    {"key": "closing", "kind": "route", "route": "#/home", "dwell": 6000,
     "lines": ["以上就是校园科创导航智能体的演示。",
               "它从真实数据出发，覆盖从信息到参赛计划的闭环。"]},
]


def ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(scenes, out: Path) -> None:
    blocks = [
        "[Script Info]", "ScriptType: v4.00+",
        f"PlayResX: {WIDTH}", f"PlayResY: {HEIGHT}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,SimHei,30,&H00FFFFFF,&H00000000,&H00000000,&H99000000,"
        "0,0,0,0,100,100,0,0,1,3,0,2,40,40,60,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Text",
    ]
    n = 0
    for sc in scenes:
        start = sc.get("start", 0.0)
        end = sc.get("end", start + 2.0)
        lines = sc.get("lines") or [""]
        if end - start < 1.0:
            end = start + max(1.0, 1.2 * len(lines))
        span = (end - start) / max(1, len(lines))
        for i, ln in enumerate(lines):
            s = start + i * span
            e = end if i == len(lines) - 1 else start + (i + 1) * span
            txt = ln.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            blocks.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Default,{txt}")
            n += 1
    out.write_text("\n".join(blocks) + "\n", encoding="utf-8")
    print(f"ASS_WRITTEN {out} cues={n}", flush=True)


def main() -> None:
    REC_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(REC_DIR),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept("local-dev-admin-token"))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(800)
        t0 = time.time()

        def go(route: str):
            page.evaluate(f"location.hash={route!r}")
            page.wait_for_timeout(700)

        for sc in SCENES:
            kind = sc["kind"]
            try:
                if kind == "login":
                    page.wait_for_selector("#login-overlay:not(.hidden)", timeout=8000)
                    sc["start"] = time.time() - t0
                    page.wait_for_timeout(1500)
                    page.fill("#login-username", "test")
                    page.fill("#login-password", "test123")
                    page.click("#login-form button[type=submit]")
                    page.wait_for_timeout(1700)
                    sc["end"] = time.time() - t0
                else:
                    if kind == "route":
                        go(sc["route"]); page.wait_for_timeout(600)
                    elif kind == "scroll":
                        page.mouse.wheel(0, sc["px"]); page.wait_for_timeout(500)
                    elif kind == "click_test_type":
                        page.evaluate("location.hash='#/profile'")
                        page.wait_for_timeout(1000)
                        btns = page.locator("#test-types .test-type-card, #test-types button")
                        if btns.count() > sc["idx"]:
                            btns.nth(sc["idx"]).click()
                        page.wait_for_timeout(1000)
                    elif kind == "open_detail":
                        btn = page.locator("#recommend-list .detail-btn").first
                        if btn.count():
                            btn.click()
                        else:
                            go("#/hall")
                        page.wait_for_timeout(1200)
                    elif kind == "agent_ask":
                        page.evaluate("location.hash='#/agent'")
                        page.wait_for_timeout(600)
                        page.fill("#agent-q", sc["q"])
                        page.click("#agent-send")
                        page.wait_for_timeout(500)
                    elif kind == "hall_search":
                        page.evaluate("location.hash='#/hall'")
                        page.wait_for_timeout(800)
                        page.fill("#hall-search", sc["q"])
                        try:
                            page.wait_for_selector("#hall-list .comp-card", timeout=9000)
                        except Exception:
                            pass
                        page.wait_for_timeout(800)
                    elif kind == "admin":
                        page.click("#admin-entry-btn")
                        try:
                            page.wait_for_selector("#quality-dashboard", timeout=9000)
                        except Exception:
                            pass
                        page.wait_for_timeout(800)
                    elif kind == "admin_quality":
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(600)
                    print("OK", sc["key"], flush=True)
                    page.wait_for_timeout(300)
                    sc["start"] = max(0.0, time.time() - t0)
                    page.wait_for_timeout(sc["dwell"])
                    sc["end"] = time.time() - t0
            except Exception as e:  # noqa: BLE001
                print("FAIL", sc["key"], repr(e), flush=True)
                now = time.time() - t0
                sc.setdefault("start", max(0.0, now))
                sc["end"] = sc["start"] + max(1.0, sc.get("dwell", 2000) / 1000.0)

        # 1) 先落盘时间轴与字幕（此时视频仍在外录，即使随后卡死也已保住成果）
        TIMINGS.write_text(json.dumps(
            [{"key": s["key"], "start": round(s.get("start", 0), 3),
              "end": round(s.get("end", 0), 3)} for s in SCENES],
            ensure_ascii=False, indent=2), encoding="utf-8")
        build_ass(SCENES, ASS)
        print("TIMINGS_WRITTEN", flush=True)

        # 2) 记录视频文件路径（playwright 已把它写在 record_video_dir）
        try:
            vpath = page.video.path()
            print("VIDEO_PATH", vpath, flush=True)
        except Exception as e:  # noqa: BLE001
            vpath = None
            print("VIDEO_PATH_WARN", repr(e), flush=True)

        # 3) 关闭页面以 finalize 视频（偶发卡死也不影响已落盘的字幕/时间轴）
        try:
            page.close()
        except Exception as e:  # noqa: BLE001
            print("PAGE_CLOSE_WARN", repr(e), flush=True)

        # 4) 复制为 demo_rec.webm（纯文件复制，不依赖 playwright）
        import shutil
        try:
            if vpath and os.path.exists(vpath):
                shutil.copyfile(vpath, str(WEBM))
            else:
                cands = sorted(REC_DIR.glob("*.webm"), key=lambda f: f.stat().st_mtime)
                if cands:
                    shutil.copyfile(str(cands[-1]), str(WEBM))
        except Exception as e:  # noqa: BLE001
            print("COPY_WARN", repr(e), flush=True)
        print("VIDEO_SAVED", os.path.getsize(str(WEBM)) if WEBM.exists() else -1, flush=True)

    # 强制退出，绕开 Windows 上偶发的浏览器关闭卡死
    os._exit(0)


if __name__ == "__main__":
    main()

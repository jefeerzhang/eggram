"""
最小烟雾测试：验 3 件事
  1. 页面无 console error
  2. GSAP timeline 创建成功（window.__timelines 有对应 key）
  3. 关键 DOM 元素渲染了

不录像、不拼 mp4、不动 make_video.py。
"""
import os
import sys
from playwright.sync_api import sync_playwright

BLOCKS = [
    ("beat-freeze-cut.html", "beat-freeze-cut", "#bfc-root"),
    ("cinematic-zoom.html",  "main",            "#root"),
    ("bar-chart-race.html",  "bar-chart-race",  "#bcr-root"),
]

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    failures = 0
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()  # 无本机 Chrome 时回退 playwright chromium
        for fname, timeline_key, root_sel in BLOCKS:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            errors = []
            page.on("pageerror", lambda exc, e=errors: e.append(f"pageerror: {exc}"))
            page.on("console", lambda msg, e=errors:
                    e.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)

            url = f"file://{os.path.join(HERE, fname).replace(os.sep, '/')}"
            page.goto(url, wait_until="load", timeout=30_000)
            page.wait_for_timeout(800)  # GSAP CDN + script 执行

            tl_count = page.evaluate(
                "(k) => (window.__timelines && window.__timelines[k]) ? 1 : 0",
                timeline_key,
            )
            root_visible = page.evaluate(
                "(sel) => { const el = document.querySelector(sel); "
                "return el ? el.getBoundingClientRect().width : 0; }",
                root_sel,
            )

            ok = (tl_count == 1) and (root_visible > 0) and (not errors)
            tag = "PASS" if ok else "FAIL"
            print(f"[{tag}] {fname}")
            print(f"        timeline[{timeline_key!r}]={tl_count}, "
                  f"root_width={root_visible:.0f}")
            if errors:
                for e in errors[:5]:
                    print(f"        ! {e}")
                failures += 1
            page.close()
        browser.close()
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

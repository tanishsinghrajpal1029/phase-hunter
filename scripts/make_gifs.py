"""Record GIFs of the prototype for the README and the presentation video.

    python3 scripts/make_gifs.py          # needs playwright + pillow

Writes figures/gameplay.gif (a full round: pings, reveal, reaction cards) and
figures/memes.gif (the reaction cards cycling). Everything recorded is our own
art and our own game - no third-party footage.
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAME = (ROOT / "game/index.html").as_uri()
FIGURES = ROOT / "figures"
FRAME_MS = 90


def save(frames: list[bytes], path: pathlib.Path, width: int, ms: int = FRAME_MS) -> None:
    import io
    images = []
    for raw in frames:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
        images.append(image.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG))
    if len(frames) > 1 and len(set(frames)) == 1:
        raise SystemExit(f"{path.name}: every frame is identical - the clip region is probably wrong")
    images[0].save(path, save_all=True, append_images=images[1:], duration=ms, loop=0, optimize=True)
    written = Image.open(path)
    print(f"{path.name}: {len(images)} captured, {written.n_frames} kept, {path.stat().st_size/1e6:.2f} MB")


def dismiss(page) -> None:
    """Close the rules sheet that opens on a first visit, and stop the tutorial."""
    page.evaluate("""() => {
      document.getElementById('info')?.classList.remove('show');
      if (typeof stopTutorial === 'function' && typeof tutorial !== 'undefined' && tutorial) stopTutorial();
    }""")
    page.wait_for_timeout(200)


def gameplay(page) -> list[bytes]:
    frames: list[bytes] = []
    board = page.locator("#board").bounding_box()
    panel = {"x": 0, "y": 0, "width": 1000, "height": 680}

    def grab(n: int = 1) -> None:
        for _ in range(n):
            frames.append(page.screenshot(clip=panel))
            page.wait_for_timeout(40)

    grab(4)
    page.click('[data-shots="20"]')
    for fx, fy in [(0.22, 0.78), (0.33, 0.62), (0.44, 0.52), (0.58, 0.46), (0.72, 0.62), (0.86, 0.74)]:
        page.mouse.click(board["x"] + board["width"] * fx, board["y"] + board["height"] * fy)
        page.wait_for_timeout(120)
        grab(3)
    page.click('[data-shots="500"]')
    for fx, fy in [(0.5, 0.35), (0.65, 0.8)]:
        page.mouse.click(board["x"] + board["width"] * fx, board["y"] + board["height"] * fy)
        page.wait_for_timeout(120)
        grab(3)
    # drag one boundary handle down, then reveal
    page.mouse.move(board["x"] + board["width"] * 0.08, board["y"] + board["height"] * 0.36)
    page.mouse.down()
    for step in range(6):
        page.mouse.move(board["x"] + board["width"] * 0.08,
                        board["y"] + board["height"] * (0.36 + 0.035 * step))
        grab(1)
    page.mouse.up()
    grab(2)
    page.click("#reveal")
    page.wait_for_timeout(120)
    grab(14)
    return frames


def memes(page) -> list[bytes]:
    page.evaluate("""() => {
      document.querySelector('main').style.display='none';
      const box=document.getElementById('cards');
      box.style.cssText='position:static;padding:20px;display:block;min-height:150px';
    }""")
    ids = page.evaluate("Object.keys(CARDS)")

    def show(card: str, caption: str) -> None:
        page.evaluate("""([id, caption]) => {
          document.querySelectorAll('.rc').forEach(e=>e.remove());
          lastCard = 0; react(id, caption);
        }""", [card, caption])
        page.wait_for_timeout(200)

    # Measure the cards rather than assuming where they land. A hard-coded clip is what let this
    # script quietly record the header instead of the art after the layout moved.
    boxes = []
    for card in ids:
        show(card, "measuring")
        boxes.append(page.locator(".rc").first.bounding_box())
    clip = {"x": round(min(b["x"] for b in boxes) - 6), "y": round(min(b["y"] for b in boxes) - 6),
            "width": round(max(b["width"] for b in boxes) + 12),
            "height": round(max(b["height"] for b in boxes) + 12)}

    frames: list[bytes] = []
    for card in ids:
        show(card, "fires on: " + card.replace("_", " "))
        for _ in range(7):
            frames.append(page.screenshot(clip=clip))
            page.wait_for_timeout(60)
    return frames


def main() -> None:
    FIGURES.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 700})
        page.goto(GAME)
        page.wait_for_timeout(900)
        dismiss(page)
        save(gameplay(page), FIGURES / "gameplay.gif", 720)
        page.reload()
        page.wait_for_timeout(700)
        dismiss(page)
        save(memes(page), FIGURES / "memes.gif", 460, ms=110)
        browser.close()


if __name__ == "__main__":
    main()

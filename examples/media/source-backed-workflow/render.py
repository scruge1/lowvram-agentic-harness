"""STUAIM-styled illustrated replay of the public scripted offline fixture.

This is editorial artwork generated from public test evidence. It is not a
screenshot or screen recording of the unreleased desktop, a local LLM run,
or an autonomous worker session. The mark and wordmark are copied from
the retained STUAIM branding review. No font binaries are redistributed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
W, H, FPS, DURATION = 1920, 1080, 24, 22
BG = (24, 27, 27)
SIDEBAR = (21, 24, 23)
PANEL = (30, 34, 33)
PANEL2 = (34, 39, 36)
TEXT = (231, 233, 232)
MUTED = (149, 159, 154)
DIM = (108, 120, 113)
ACCENT = (177, 208, 193)
BORDER = (56, 65, 61)
FAILED = (217, 132, 121)
SCHEMA = "lowvram-offline-workflow-capture/v1"
FONTS: dict[tuple[int, bool, bool], ImageFont.FreeTypeFont] = {}


def f(size: int, bold: bool = False, mono: bool = False):
    key = (size, bold, mono)
    if key not in FONTS:
        optional = os.getenv("STUAIM_RENDER_FONT")
        opts = [optional] if optional and not mono else []
        if sys.platform == "win32":
            base = Path("C:/Windows/Fonts")
            opts += [
                str(base / s)
                for s in (
                    ["consola.ttf"]
                    if mono
                    else ["segoeuib.ttf", "arialbd.ttf"]
                    if bold
                    else ["segoeui.ttf", "arial.ttf"]
                )
            ]
        else:
            base = Path("/usr/share/fonts/truetype/dejavu")
            opts += [
                str(base / s)
                for s in (
                    ["DejaVuSansMono.ttf"]
                    if mono
                    else ["DejaVuSans-Bold.ttf"]
                    if bold
                    else ["DejaVuSans.ttf"]
                )
            ]
        chosen = next((p for p in opts if p and Path(p).is_file()), None)
        FONTS[key] = (
            ImageFont.truetype(chosen, size) if chosen else ImageFont.load_default()
        )
    return FONTS[key]


def ease(x: float) -> float:
    x = min(1, max(0, x))
    return x * x * (3 - 2 * x)


def scene_alpha(t, start, end):
    fade = 0.5
    return ease((t - start) / fade) * (1 - ease((t - end + fade) / fade))


def txt(d, pos, value, size=28, color=TEXT, bold=False, mono=False):
    d.text(
        (round(pos[0]), round(pos[1])),
        value,
        font=f(size, bold, mono),
        fill=(*color, 255),
    )


def rect(d, box, fill=PANEL, border=BORDER, radius=16):
    d.rounded_rectangle(
        box, radius=radius, fill=(*fill, 255), outline=(*border, 255), width=2
    )


def heading(d, eyebrow, title, subtitle=None):
    txt(d, (425, 246), eyebrow.upper(), 23, ACCENT, bold=True)
    txt(d, (422, 321), title, 66, TEXT, bold=True)
    if subtitle:
        txt(d, (426, 423), subtitle, 30, MUTED)


def icon(d, x, y, kind, color=MUTED):
    w = 2
    if kind == "chat":
        d.rounded_rectangle(
            (x, y, x + 24, y + 19), radius=6, outline=(*color, 255), width=w
        )
        d.line((x + 6, y + 19, x + 3, y + 25), fill=(*color, 255), width=w)
    elif kind == "home":
        d.line(
            (x + 1, y + 12, x + 13, y + 1, x + 25, y + 12), fill=(*color, 255), width=w
        )
        d.line(
            (x + 5, y + 11, x + 5, y + 23, x + 21, y + 23, x + 21, y + 11),
            fill=(*color, 255),
            width=w,
        )
    elif kind == "board":
        d.rectangle((x + 1, y + 2, x + 22, y + 23), outline=(*color, 255), width=w)
        d.line((x + 12, y + 2, x + 12, y + 23), fill=(*color, 255), width=w)
    elif kind == "book":
        d.line(
            (x + 2, y + 3, x + 11, y + 6, x + 11, y + 23, x + 2, y + 20),
            fill=(*color, 255),
            width=w,
        )
        d.line(
            (x + 12, y + 6, x + 22, y + 3, x + 22, y + 20, x + 12, y + 23),
            fill=(*color, 255),
            width=w,
        )
    else:
        d.ellipse((x + 4, y + 4, x + 22, y + 22), outline=(*color, 255), width=w)
        for dx in (0, 26):
            d.line((x + dx, y + 11, x + dx, y + 17), fill=(*color, 255), width=w)


def shell_background():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im, "RGB")
    d.rectangle((0, 0, 305, H), fill=SIDEBAR)
    d.line((305, 0, 305, H), fill=BORDER, width=1)
    d.line((305, 91, W, 91), fill=BORDER, width=1)
    d.line((0, 1000, W, 1000), fill=BORDER, width=1)
    for y, name, symbol in [
        (235, "Chat", "chat"),
        (301, "Projects", "home"),
        (367, "Board", "board"),
        (433, "Knowledge", "book"),
        (499, "Models", "model"),
    ]:
        if name == "Board":
            d.rounded_rectangle((24, y - 9, 281, y + 44), radius=10, fill=PANEL)
        icon(d, 52, y, symbol, ACCENT if name == "Board" else MUTED)
        txt(
            d,
            (102, y - 2),
            name,
            23,
            TEXT if name == "Board" else MUTED,
            bold=name == "Board",
        )
    txt(d, (35, 176), "WORKSPACE", 16, DIM, bold=True)
    txt(d, (38, 876), "LOCAL EXAMPLE", 17, MUTED)
    txt(d, (38, 917), "Script worker", 20, TEXT)
    txt(d, (350, 34), "Workspace    /    Offline verifier example", 23, MUTED)
    txt(d, (1520, 34), "ILLUSTRATED REPLAY", 19, DIM)
    txt(d, (350, 1025), "Examples / enforced-task", 19, MUTED)
    txt(d, (1170, 1025), "Scripted fixture. No local LLM used.", 19, MUTED)
    return im


def apply_brand(im):
    brand = ROOT / "docs/media/stuaim/stuaim-horizontal-dark.png"
    if not brand.is_file():
        raise ValueError("Exact retained STUAIM brand asset missing")
    original = Image.open(brand).convert("RGB")
    scaled = original.resize((273, 77), Image.Resampling.LANCZOS)
    im.paste(scaled, (13, 21))


def card(d, y, label, state, note, good):
    rect(d, (430, y, 1800, y + 167), fill=PANEL2 if good else PANEL)
    tag = ACCENT if good else FAILED
    txt(d, (467, y + 23), label.upper(), 22, MUTED, bold=True)
    txt(d, (466, y + 77), state, 42, tag, bold=True)
    txt(d, (930, y + 40), note, 31, TEXT, mono=True)
    d.ellipse((1713, y + 54, 1750, y + 91), outline=tag, width=3)


def scene_intro(d, t, evidence):
    heading(d, "Enforced task / public harness", "Offline verifier example")
    txt(
        d,
        (426, 455),
        "The example runs a scripted worker with independent output checks.",
        30,
        MUTED,
    )
    rect(d, (428, 595, 1800, 810))
    txt(d, (470, 630), "TASK", 21, ACCENT, bold=True)
    txt(d, (470, 697), evidence["task"], 40, TEXT, mono=True)
    txt(d, (470, 761), "One requirement. Two recorded attempts.", 28, MUTED)


def scene_scope(d, t, evidence):
    heading(d, "Task contract", "Source-bound task")
    rect(d, (426, 532, 1800, 824))
    txt(d, (474, 565), "TASK ID", 19, MUTED)
    txt(d, (474, 611), evidence["task"], 36, TEXT, mono=True)
    txt(d, (474, 697), "Requirement", 26, MUTED)
    txt(d, (800, 697), "1 admitted", 30, TEXT, bold=True)
    txt(d, (474, 763), "Verifier", 26, MUTED)
    txt(d, (800, 763), "Independent", 30, ACCENT, bold=True)


def scene_attempts(d, t, evidence):
    heading(d, "Task execution", "Verification results")
    workflow = evidence["workflow"]
    if t >= 8.75:
        card(
            d,
            518,
            "Attempt 01",
            "Rejected",
            f"verifier exit  {workflow[1]['verifier_exit_code']}",
            False,
        )
    if t >= 10.65:
        card(
            d,
            717,
            "Attempt 02",
            "Accepted",
            f"verifier exit  {workflow[3]['verifier_exit_code']}",
            True,
        )


def scene_accepted(d, t, evidence):
    heading(d, "Project state", "Result recorded")
    rect(d, (426, 535, 1800, 830))
    txt(d, (474, 573), "Authority", 21, MUTED)
    txt(
        d,
        (474, 621),
        evidence["result"]["authority_cap"].upper(),
        72,
        ACCENT,
        bold=True,
    )
    d.line((940, 576, 940, 791), fill=BORDER, width=2)
    txt(d, (1003, 581), "accepted    true", 35, TEXT, mono=True)
    txt(d, (1003, 665), "complete    true", 35, TEXT, mono=True)
    txt(d, (1003, 751), "stage       verified", 33, ACCENT, mono=True)
    txt(d, (480, 752), "Local acceptance only", 25, MUTED)


def scene_reproduce(d, t, evidence):
    heading(d, "Reproduce the test", "Run the public example")
    txt(d, (426, 457), "Source and checks are included in this repository.", 30, MUTED)
    rect(d, (426, 574, 1800, 779))
    txt(d, (470, 607), "COMMAND", 21, ACCENT, bold=True)
    txt(
        d,
        (470, 681),
        "python examples/media/source-backed-workflow/capture.py",
        27,
        TEXT,
        mono=True,
    )
    txt(d, (430, 866), "scruge1/lowvram-agentic-harness", 25, MUTED)


def frame(t, evidence, background):
    im = background.copy().convert("RGBA")
    scenes = [
        (0.0, 4.40, scene_intro),
        (4.40, 8.75, scene_scope),
        (8.75, 14.20, scene_attempts),
        (14.20, 18.70, scene_accepted),
        (18.70, 22.10, scene_reproduce),
    ]
    for start, end, fn in scenes:
        a = scene_alpha(t, start, end)
        if a <= 0:
            continue
        layer = Image.new("RGBA", (W, H))
        draw = ImageDraw.Draw(layer, "RGBA")
        fn(draw, t, evidence)
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
        im = Image.alpha_composite(im, layer)
    # Preserve the actual wordmark above all scene transitions.
    im = im.convert("RGB")
    apply_brand(im)
    d = ImageDraw.Draw(im)
    pct = min(1, max(0, t / DURATION))
    d.rounded_rectangle((351, 982, 1813, 988), radius=3, fill=BORDER)
    d.rounded_rectangle((351, 982, 351 + round(1462 * pct), 988), radius=3, fill=ACCENT)
    return im


def validate(evidence):
    if not (
        evidence.get("schema") == SCHEMA
        and evidence.get("kind") == "scripted_offline_fixture"
        and evidence.get("product_ui_captured") is False
        and evidence.get("live_model_invoked") is False
        and evidence.get("result", {}).get("authority_cap") == "tested"
        and evidence.get("result", {}).get("accepted") is True
        and evidence.get("result", {}).get("complete") is True
        and evidence.get("workflow", [{}, {}])[1].get("status") == "rejected"
        and evidence.get("workflow", [{}, {}, {}, {}])[3].get("status") == "accepted"
    ):
        raise ValueError("Refuse unsupported workflow claims")


def render_video(bg, evidence, target):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-threads",
        "4",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(target),
    ]
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(DURATION * FPS):
            child.stdin.write(frame(i / FPS, evidence, bg).tobytes())
            if (i + 1) % 96 == 0:
                print(json.dumps({"rendered_frames": i + 1}), flush=True)
        child.stdin.close()
        status = child.wait(timeout=180)
        if status:
            raise ValueError(child.stderr.read().decode("utf-8", "replace")[-1000:])
    except BaseException:
        child.kill()
        child.wait()
        raise
    return {
        "bytes": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--render-video", action="store_true")
    ap.add_argument("--review-frames", action="store_true")
    args = ap.parse_args(argv)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    validate(evidence)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bg = shell_background()
    poster = args.output_dir / "workflow-poster.png"
    frame(12.0, evidence, bg).save(poster, optimize=True)
    if args.review_frames:
        for t in (2.5, 6, 12, 16, 20.5):
            frame(t, evidence, bg).save(
                args.output_dir / f"review-{round(t * 10):03d}.png", optimize=True
            )
    if args.render_video:
        target = args.output_dir / "source-backed-workflow.mp4"
        info = render_video(bg, evidence, target)
        print(json.dumps({"video": target.name, **info}, sort_keys=True))


if __name__ == "__main__":
    main()

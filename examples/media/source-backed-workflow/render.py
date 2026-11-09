"""Original source-backed motion graphic, not an actual app or desktop capture.

Uses the retained Garden Brain creative method: a source-first brief,
editable scene code, grounded layout, motivated motion and moving review.
All artwork and animation here are original. No old Garden Brain visuals,
third-party fonts, stock audio or proprietary templates are redistributed.

Requires Pillow at authoring time and ffmpeg only to create the silent MP4.
Never invoked by the core installer or acceptance gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, DURATION = 1920, 1080, 24, 22
WHITE = (241, 247, 248)
MUTE = (146, 166, 180)
TEAL = (119, 224, 216)
GOLD = (223, 175, 108)
RED = (239, 120, 111)
SCHEMA = "lowvram-offline-workflow-capture/v1"


def font_path(weight="regular", mono=False):
    if sys.platform == "win32":
        root = Path("C:/Windows/Fonts")
        variants = (
            ["consola.ttf"]
            if mono
            else (
                ["segoeuib.ttf", "segoeuivar.ttf", "arialbd.ttf"]
                if weight == "bold"
                else ["segoeui.ttf", "segoeuivar.ttf", "arial.ttf"]
            )
        )
    else:
        root = Path("/usr/share/fonts/truetype/dejavu")
        variants = (
            ["DejaVuSansMono.ttf"]
            if mono
            else (["DejaVuSans-Bold.ttf"] if weight == "bold" else ["DejaVuSans.ttf"])
        )
    for name in variants:
        p = root / name
        if p.is_file():
            return str(p)
    return None


FONTS = {}


def ft(size, weight="regular", mono=False):
    key = (size, weight, mono)
    if key not in FONTS:
        path = font_path(weight, mono)
        FONTS[key] = (
            ImageFont.truetype(path, size) if path else ImageFont.load_default()
        )
    return FONTS[key]


def clamp(x):
    return max(0.0, min(1.0, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def reveal(t, start, duration=0.7):
    return ease((t - start) / duration)


def scene_alpha(t, start, end, fade=0.55):
    return reveal(t, start, fade) * (1 - ease((t - end + fade) / fade))


def rgba(c, a=255):
    return (*c, max(0, min(255, int(a))))


def compose_background():
    bg = Image.new("RGBA", (W, H), (8, 13, 21, 255))
    draw = ImageDraw.Draw(bg, "RGBA")
    for y in range(0, H, 3):
        k = y / H
        draw.line(
            ((0, y), (W, y)),
            fill=(12 + round(k * 6), 19 + round(k * 5), 28 + round(k * 4), 255),
            width=3,
        )
    gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    light = ImageDraw.Draw(gl, "RGBA")
    light.ellipse((1130, 80, 2010, 1010), fill=(15, 125, 120, 105))
    light.ellipse((1370, 680, 2280, 1490), fill=(196, 111, 63, 48))
    bg = Image.alpha_composite(bg, gl.filter(ImageFilter.GaussianBlur(230)))
    draw = ImageDraw.Draw(bg, "RGBA")
    for x in range(72, W, 116):
        draw.line((x, 0, x, H), fill=(34, 53, 62, 255), width=1)
    for y in range(78, H, 116):
        draw.line((0, y, W, y), fill=(31, 46, 55, 255), width=1)
    return bg


def label(draw, xy, text, color=MUTE, size=24, letter=0, weight="regular", mono=False):
    x, y = xy
    face = ft(size, weight, mono)
    if letter:
        for ch in text:
            draw.text((round(x), round(y)), ch, font=face, fill=rgba(color))
            x += draw.textlength(ch, font=face) + letter
    else:
        draw.text((round(x), round(y)), text, font=face, fill=rgba(color))


def card(draw, box, stroke=TEAL, fill=(17, 29, 38), radius=28):
    x1, y1, x2, y2 = [int(v) for v in box]
    if x2 <= x1 or y2 <= y1:
        return
    draw.rounded_rectangle(
        (x1 + 10, y1 + 16, x2 + 10, y2 + 16), radius=radius, fill=(0, 0, 0, 56)
    )
    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=radius,
        fill=rgba(fill, 242),
        outline=rgba(stroke, 110),
        width=2,
    )


def node(draw, x, y, color=TEAL, r=18, alpha=255):
    draw.ellipse(
        (x - r - 9, y - r - 9, x + r + 9, y + r + 9),
        outline=rgba(color, alpha * 0.26),
        width=1,
    )
    draw.ellipse(
        (x - r, y - r, x + r, y + r),
        fill=rgba((13, 30, 33), alpha),
        outline=rgba(color, alpha),
        width=3,
    )
    draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=rgba(color, alpha))


def graph(draw, t, opacity=1):
    coords = [
        (1245, 282),
        (1470, 400),
        (1335, 610),
        (1650, 645),
        (1750, 340),
        (1545, 825),
    ]
    edges = [(0, 1), (1, 2), (1, 4), (2, 3), (3, 4), (3, 5)]
    for i, j in edges:
        draw.line(
            (*coords[i], *coords[j]), fill=(124, 192, 193, round(55 * opacity)), width=2
        )
    for i, (x, y) in enumerate(coords):
        c = TEAL if i in (0, 1, 3) else GOLD
        node(
            draw,
            x,
            y + 1.8 * math.sin(t * 0.8 + i * 0.7),
            c,
            r=14 + 2 * math.sin(t * 0.7 + i),
            alpha=int(190 * opacity),
        )
    phase = (t * 0.22) % len(edges)
    i = min(len(edges) - 1, int(phase))
    u = phase - i
    p, q = edges[i]
    x1, y1 = coords[p]
    x2, y2 = coords[q]
    x, y = x1 + (x2 - x1) * u, y1 + (y2 - y1) * u
    draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=rgba(WHITE, 160 * opacity))


def common(draw, t):
    label(
        draw,
        (108, 76),
        "LOW-VRAM  /  AGENTIC HARNESS",
        TEAL,
        24,
        letter=2,
        weight="bold",
    )
    label(draw, (1284, 77), "OFFLINE  •  SOURCE-BOUND", (192, 207, 213), 21, letter=1)
    draw.line((108, 121, 1812, 121), fill=(53, 77, 83, 255), width=2)
    draw.line((108, 972, 1812, 972), fill=(49, 69, 76, 255), width=2)
    label(
        draw,
        (108, 997),
        "REAL SCRIPTED FIXTURE   /   NOT A DESKTOP SCREEN RECORDING",
        (155, 176, 188),
        19,
    )
    draw.rounded_rectangle((108, 1053, 1812, 1058), radius=3, fill=(52, 69, 77, 255))
    end = 108 + int(1704 * clamp(t / DURATION))
    if end > 108:
        draw.rounded_rectangle((108, 1053, end, 1058), radius=3, fill=rgba(TEAL))


def hero(draw, t):
    shift = 34 * (1 - reveal(t, 0, 0.85))

    def L(x, y, text, color=WHITE, size=40, **kw):
        label(draw, (x + shift, y), text, color, size, **kw)

    L(114, 244, "THE VERIFICATION PROBLEM", TEAL, 24, letter=2, weight="bold")
    L(108, 316, "Agents can write the work.", WHITE, 75, weight="bold")
    L(108, 414, "Only evidence can", WHITE, 89, weight="bold")
    L(108, 515, "complete it.", TEAL, 89, weight="bold")
    L(112, 670, "A real portable SSOT example: rejected output,", MUTE, 32)
    L(112, 717, "corrective retry, independent acceptance.", MUTE, 32)
    card(draw, (110, 823, 754, 902), stroke=GOLD, radius=18)
    L(143, 841, "ONE FIXTURE  •  TWO ATTEMPTS  •  ONE CHECK", GOLD, 23, weight="bold")


def source_scene(draw, t):
    dy = 35 * (1 - reveal(t, 4.4, 0.7))
    label(
        draw, (110, 205 + dy), "01    ADMIT THE TASK", TEAL, 24, letter=2, weight="bold"
    )
    label(
        draw,
        (108, 290 + dy),
        "A project owns the requirement.",
        WHITE,
        70,
        weight="bold",
    )
    label(draw, (112, 404 + dy), "Source files and task scope are fixed", MUTE, 33)
    label(draw, (112, 451 + dy), "before the worker can claim a result.", MUTE, 33)
    card(draw, (112, 562 + dy, 1055, 840 + dy), stroke=GOLD)
    label(draw, (150, 594 + dy), "SSOT TASK CONTRACT", GOLD, 25, letter=1)
    label(
        draw,
        (150, 656 + dy),
        "offline-enforced-example",
        WHITE,
        38,
        weight="bold",
        mono=True,
    )
    label(draw, (150, 730 + dy), "1  source-bound requirement", MUTE, 28)
    label(draw, (150, 776 + dy), "Independent verifier required", TEAL, 28)
    node(draw, 1360, 570, TEAL, r=25)
    label(draw, (1434, 548), "SOURCE", WHITE, 24, weight="bold")
    label(draw, (1434, 592), "pinned input", MUTE, 22)


def retry_scene(draw, t):
    label(
        draw,
        (110, 204),
        "02    DETECT • CORRECT • RECHECK",
        TEAL,
        24,
        letter=2,
        weight="bold",
    )
    label(draw, (108, 289), "A passing command is not proof.", WHITE, 68, weight="bold")
    label(draw, (112, 385), "The same verifier checks every attempt.", MUTE, 32)
    p1, p2 = reveal(t, 8.75, 0.8), reveal(t, 10.7, 0.8)
    y1, y2 = 487 + round((1 - p1) * 65), 700 + round((1 - p2) * 68)
    card(draw, (112, y1, 1808, y1 + 170), stroke=RED, fill=(31, 25, 31))
    label(draw, (153, y1 + 23), "ATTEMPT 01", RED, 24, letter=1, weight="bold")
    label(draw, (155, y1 + 76), "REJECTED", WHITE, 51, weight="bold")
    label(draw, (990, y1 + 44), "verifier_exit_code  =  1", RED, 31, mono=True)
    label(draw, (991, y1 + 101), "Output failed the independent check", MUTE, 25)
    if p2 > 0.02:
        card(draw, (112, y2, 1808, y2 + 170), stroke=TEAL, fill=(16, 37, 40))
        label(draw, (153, y2 + 23), "ATTEMPT 02", TEAL, 24, letter=1, weight="bold")
        label(draw, (155, y2 + 76), "ACCEPTED", WHITE, 51, weight="bold")
        label(draw, (990, y2 + 44), "verifier_exit_code  =  0", TEAL, 31, mono=True)
        label(draw, (991, y2 + 101), "Corrective retry passed the same check", MUTE, 25)
    if 9.45 < t < 11.4:
        p = reveal(t, 9.5, 1.5)
        draw.line((960, 660, 960, 700), fill=rgba(GOLD, p * 180), width=4)
        node(draw, 960, 686, GOLD, r=6, alpha=int(210 * p))


def verified_scene(draw, t, evidence):
    label(
        draw,
        (110, 204),
        "03    INDEPENDENT ACCEPTANCE",
        TEAL,
        24,
        letter=2,
        weight="bold",
    )
    label(draw, (108, 292), "The host checks the result.", WHITE, 76, weight="bold")
    label(draw, (112, 389), "The worker cannot promote its own success.", MUTE, 32)
    prog = reveal(t, 14.4, 0.8)
    card(draw, (111, 502, 1810, 854), stroke=TEAL, fill=(16, 34, 40))
    label(draw, (154, 543), "LOCAL AUTHORITY", GOLD, 24, letter=1, weight="bold")
    label(draw, (148, 617), "TESTED", TEAL, 97, weight="bold")
    label(draw, (151, 768), "not externally blessed", MUTE, 26)
    draw.line((825, 560, 825, 809), fill=(119, 224, 216, 58), width=2)
    label(draw, (889, 555), "accepted     true", WHITE, 40, mono=True)
    label(draw, (889, 633), "complete     true", WHITE, 40, mono=True)
    label(draw, (889, 711), "stage        verified", TEAL, 37, mono=True)
    label(
        draw,
        (889, 790),
        "result SHA256   " + evidence["result"]["result_sha256"][:12] + "…",
        MUTE,
        26,
        mono=True,
    )
    if prog > 0:
        x, y = 732 + round(prog * 42), 636
        draw.ellipse(
            (x - 29, y - 29, x + 29, y + 29), outline=rgba(TEAL, prog * 255), width=5
        )
        draw.line(
            (x - 13, y - 2, x - 3, y + 8, x + 17, y - 14),
            fill=rgba(TEAL, prog * 255),
            width=5,
            joint="curve",
        )


def close_scene(draw, t):
    dy = 40 * (1 - reveal(t, 18.7, 0.7))
    label(
        draw,
        (111, 209 + dy),
        "REPRODUCE THE PUBLIC EXAMPLE",
        TEAL,
        26,
        letter=1.5,
        weight="bold",
    )
    label(
        draw,
        (108, 296 + dy),
        "Inspect the evidence yourself.",
        WHITE,
        74,
        weight="bold",
    )
    label(
        draw,
        (112, 404 + dy),
        "It is scripted, offline, and intentionally limited.",
        MUTE,
        31,
    )
    card(draw, (110, 541 + dy, 1812, 756 + dy), stroke=GOLD, fill=(24, 31, 39))
    label(
        draw,
        (151, 565 + dy),
        "REPRODUCIBLE COMMAND",
        GOLD,
        23,
        letter=1.6,
        weight="bold",
    )
    label(
        draw,
        (151, 632 + dy),
        "python examples/media/source-backed-workflow/capture.py",
        WHITE,
        34,
        mono=True,
    )
    label(draw, (112, 831 + dy), "github.com/scruge1/lowvram-agentic-harness", TEAL, 29)
    label(
        draw,
        (112, 893 + dy),
        "See workflow source + notes  ·  No local LLM called",
        MUTE,
        26,
    )


def frame(t, evidence, background):
    result = background.copy()
    back = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    graph(ImageDraw.Draw(back, "RGBA"), t, 0.73 if t < 4 else 0.35)
    result = Image.alpha_composite(result, back)
    # No crossfading of two text-heavy scenes. Shared visual background
    # remains in place; each scene fades through that background before
    # the next heading appears. The first sampled render exposed overlapping
    # titles at four handoffs, now prohibited by non-overlapping ranges.
    scenes = [
        (0.0, 4.40, hero),
        (4.40, 8.75, source_scene),
        (8.75, 14.20, retry_scene),
        (14.20, 18.70, lambda draw, time: verified_scene(draw, time, evidence)),
        (18.70, 22.10, close_scene),
    ]
    for start, end, painter in scenes:
        alpha = scene_alpha(t, start, end)
        if alpha <= 0:
            continue
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        painter(ImageDraw.Draw(layer, "RGBA"), t)
        layer.putalpha(layer.getchannel("A").point(lambda p: int(p * alpha)))
        result = Image.alpha_composite(result, layer)
    common(ImageDraw.Draw(result, "RGBA"), t)
    return result.convert("RGB")


def validate(evidence):
    if not (
        evidence.get("schema") == SCHEMA
        and evidence.get("kind") == "scripted_offline_fixture"
        and evidence.get("live_model_invoked") is False
        and evidence.get("product_ui_captured") is False
        and evidence.get("result", {}).get("authority_cap") == "tested"
        and evidence.get("result", {}).get("accepted") is True
        and evidence.get("result", {}).get("complete") is True
        and evidence.get("workflow", [{}, {}])[1].get("status") == "rejected"
    ):
        raise ValueError("Refusing to visualize unqualified or fabricated fixture data")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--render-video", action="store_true")
    parser.add_argument("--review-frames", action="store_true")
    args = parser.parse_args(argv)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    validate(evidence)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    background = compose_background()
    poster = args.output_dir / "workflow-poster.png"
    frame(11.8, evidence, background).save(poster, optimize=True)
    print(json.dumps({"poster": str(poster), "bytes": poster.stat().st_size}))
    if args.review_frames:
        for t in (2.1, 5.4, 12.0, 15.9, 19.9):
            frame(t, evidence, background).save(
                args.output_dir / ("review-%03d.png" % int(t * 10)), optimize=True
            )
    if args.render_video:
        target = args.output_dir / "source-backed-workflow.mp4"
        command = [
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
            "fast",
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
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for n in range(DURATION * FPS):
                child.stdin.write(frame(n / FPS, evidence, background).tobytes())
                if (n + 1) % 96 == 0:
                    print(json.dumps({"rendered_frames": n + 1}), flush=True)
            child.stdin.close()
            status = child.wait(timeout=120)
            errors = child.stderr.read().decode("utf-8", "replace")
            if status:
                raise RuntimeError("ffmpeg failed: " + errors[-1000:])
        except BaseException:
            child.kill()
            child.wait()
            raise
        print(
            json.dumps(
                {
                    "video": str(target),
                    "bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
        )


if __name__ == "__main__":
    main()

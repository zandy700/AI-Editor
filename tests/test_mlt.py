"""Render the MLT export with real `melt` and check what comes out: length, colours at known times, text, audio fades.
Run: .venv/bin/python tests/test_mlt.py   (needs melt + ffmpeg; skips with a message without melt)"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from features import ffmpeg, full_timeline  # noqa: E402
from editor import Timeline  # noqa: E402
from editor.export import export  # noqa: E402
from editor.export.mlt import SUPPORTS  # noqa: E402
from editor.timeline import FEATURES  # noqa: E402
from editor.zoom import apply_click_zoom  # noqa: E402


def render(tl, tmp):
    mlt, = export(tl, "kdenlive", tmp)
    out = tmp / f"{tl.name}.mp4"
    subprocess.run(["melt", str(mlt), "-consumer", f"avformat:{out}", "vcodec=libx264", "acodec=aac", "pix_fmt=yuv420p"],
                   check=True, capture_output=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    return out


def pixel(video, t, x, y):
    """(r, g, b) at second t, pixel (x, y)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                          "-vf", f"format=rgb24,crop=1:1:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return tuple(raw[:3])


def count(video, t, test, region):
    """How many pixels in region=(x, y, w, h) at second t satisfy test(r, g, b)."""
    x, y, w, h = region
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                          "-vf", f"format=rgb24,crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return sum(test(*raw[i:i + 3]) for i in range(0, len(raw), 3))


def info(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "default=nw=1", str(video)], capture_output=True, text=True, check=True).stdout
    return float(out.split("duration=")[1].split()[0]), {l.split("=")[1] for l in out.split() if l.startswith("codec_type")}


def level_db(video, start, dur=0.2):
    err = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(dur), "-i", str(video), "-af", "volumedetect",
                          "-vn", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(err.split("mean_volume:")[1].split("dB")[0])


def test_supports_every_feature():
    assert SUPPORTS == set(FEATURES)


def test_full_timeline(tmp):
    tl = full_timeline(tmp)
    video = render(tl, tmp)
    dur, kinds = info(video)
    assert abs(dur - tl.duration) <= 1 / tl.fps + 0.01, (dur, tl.duration)
    assert kinds == {"video", "audio"}
    cx, cy = tl.width // 2, tl.height // 2
    r, g, b = pixel(video, 0.05, cx, cy)
    assert r < 60 and g < 20 and b < 20, f"fade-in starts near black: {(r, g, b)}"
    r, g, b = pixel(video, 0.8, cx, cy)
    assert r > 200 and b < 40, f"then full red: {(r, g, b)}"
    r, g, b = pixel(video, 3.5, cx, cy)
    assert r > 80 and b > 80 and g < 60, f"crossfade is a red/blue blend: {(r, g, b)}"
    r, g, b = pixel(video, 5, cx, cy)
    assert b > 200 and r < 40, f"blue clip: {(r, g, b)}"
    r, g, b = pixel(video, 8, cx, cy)
    assert g > 100 and r < 40 and b < 40, f"still image: {(r, g, b)}"
    r, g, b = pixel(video, 10, cx, cy)
    assert r > 200 and g < 60, f"sped-up clip: {(r, g, b)}"
    bottom = (0, int(tl.height * 0.8), tl.width, int(tl.height * 0.2))
    assert count(video, 2, lambda r, g, b: r > 200 and g > 200 and b < 90, bottom) > 200, "yellow 'Hello' at 2 s"
    assert count(video, 1.5, lambda r, g, b: r > 200 and g > 200 and b < 90, bottom) > 0
    assert count(video, 0.5, lambda r, g, b: r > 200 and g > 200 and b < 90, bottom) == 0, "no title before 1 s"
    bright_yellow = lambda r, g, b: r > 200 and g > 200 and b < 90
    assert count(video, 1.1, bright_yellow, bottom) == 0, "title fades in over 0.5 s"
    assert count(video, 2.0, bright_yellow, bottom) > 200
    assert count(video, 2.9, bright_yellow, bottom) == 0, "and fades out"
    assert count(video, 6, lambda r, g, b: r > 200 and g > 200 and b > 200, bottom) > 200, "white 'World' at 6 s"
    assert pixel(video, 8, 20, cy) == (0, 0, 0), "4:3 still keeps its shape: black side bars"


def small(name):
    return Timeline(name, width=640, height=360, fps=30)


def test_zoom(tmp):
    pattern = tmp / "box.mp4"       # black frame, white box in the top-left sixth
    ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=30:d=4,drawbox=x=0:y=0:w=106:h=60:color=white:t=fill",
           "-pix_fmt", "yuv420p", str(pattern))
    tl = small("zoom")
    apply_click_zoom(tl.add_clip(pattern, dur=3), [1.0])      # 1.0 at 0.75 s, 1.5x at 1.0-1.6 s, back at 1.85 s
    video = render(tl, tmp)
    assert pixel(video, 0.2, 50, 30)[0] > 200, "unzoomed: box visible"
    assert pixel(video, 1.3, 50, 30)[0] < 60, "zoomed 1.5x about the centre: box pushed off-screen"
    assert pixel(video, 2.5, 50, 30)[0] > 200, "back to normal"


def test_speed_and_trim(tmp):
    colors = tmp / "cycle.mp4"       # red 0-2 s, green 2-4 s, blue 4-6 s
    ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=30:d=6,"
           "geq=r='255*lt(T,2)':g='255*between(T,2,4)':b='255*gte(T,4)':a=255", "-pix_fmt", "yuv420p", str(colors))
    tl = small("speed")
    tl.add_clip(colors, dur=2, src=0, speed=2)       # source 0-4 s in 2 s: red then green
    tl.add_clip(colors, dur=1, src=4)                # source 4-5 s: blue
    video = render(tl, tmp)
    assert abs(info(video)[0] - 3) < 0.1
    r, g, b = pixel(video, 0.5, 320, 180)
    assert r > 200 and g < 50, f"first half of the 2x clip is red: {(r, g, b)}"
    r, g, b = pixel(video, 1.5, 320, 180)
    assert g > 200 and r < 50, f"second half is green (2x reached source 3 s): {(r, g, b)}"
    r, g, b = pixel(video, 2.5, 320, 180)
    assert b > 200 and r < 50, f"trimmed clip starts at source 4 s: {(r, g, b)}"


def test_opacity_and_tracks(tmp):
    red, blue = tmp / "r.mp4", tmp / "b.mp4"
    for f, c in [(red, "red"), (blue, "blue")]:
        ffmpeg("-f", "lavfi", "-i", f"color={c}:s=640x360:r=30:d=4", "-pix_fmt", "yuv420p", str(f))
    tl = small("opacity")
    tl.add_clip(red, dur=3)
    tl.add_clip(blue, dur=1, start=1, track=1, opacity=0.5)
    video = render(tl, tmp)
    r, g, b = pixel(video, 1.5, 320, 180)
    assert 90 < r < 170 and 90 < b < 170 and g < 50, f"50% blue over red: {(r, g, b)}"
    r, g, b = pixel(video, 0.5, 320, 180)
    assert r > 200 and b < 40, "overlay not there yet"
    r, g, b = pixel(video, 2.5, 320, 180)
    assert r > 200 and b < 40, "overlay gone"


def test_crossfade_chain_both_directions(tmp):
    clips = []
    for c in ("red", "green", "blue"):
        p = tmp / f"{c}.mp4"
        ffmpeg("-f", "lavfi", "-i", f"color={c}:s=640x360:r=30:d=4", "-pix_fmt", "yuv420p", str(p))
        clips.append(p)
    tl = small("chain")
    tl.add_clip(clips[0], dur=2)
    tl.add_clip(clips[1], dur=2, crossfade=1)         # overlaps red at 1-2 s
    tl.add_clip(clips[2], dur=2, crossfade=1)         # overlaps green at 2-3 s
    video = render(tl, tmp)
    assert abs(info(video)[0] - 4) < 0.1, "overlaps shorten the timeline"
    early, late = pixel(video, 1.25, 320, 180), pixel(video, 1.75, 320, 180)
    assert early[0] > early[1] and late[1] > late[0], f"red -> green moves forward: {early} {late}"
    early, late = pixel(video, 2.25, 320, 180), pixel(video, 2.75, 320, 180)
    assert early[1] > early[2] and late[2] > late[1], f"green -> blue moves forward: {early} {late}"
    assert pixel(video, 0.5, 320, 180)[0] > 200 and pixel(video, 3.5, 320, 180)[2] > 200


def test_audio_fades_and_volume(tmp):
    tone = tmp / "tone.mp3"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(tone))
    tl = small("audio")
    tl.add_audio(tone, dur=8, fade_in=1, fade_out=2)
    video = render(tl, tmp)
    mid, start, end = level_db(video, 3.5), level_db(video, 0.0, 0.15), level_db(video, 7.8, 0.15)
    assert start < mid - 12, f"fade-in: {start} vs {mid} dB"
    assert end < mid - 12, f"fade-out: {end} vs {mid} dB"
    quiet = small("audio_half")
    quiet.add_audio(tone, dur=4, volume=0.5)
    half = level_db(render(quiet, tmp), 1.0)
    assert -7.5 < half - mid < -4.5, f"volume 0.5 is about -6 dB: {half - mid}"


if __name__ == "__main__":
    if not shutil.which("melt"):
        print("skipped (melt not installed: brew install mlt)")
        sys.exit(0)
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            tmp = Path(tempfile.mkdtemp())
            fn(*([tmp] if fn.__code__.co_argcount else []))
            print("ok", name)

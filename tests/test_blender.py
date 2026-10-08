"""Render exported Blender scripts headless and check the pixels and audio levels, not just the script.
Run: .venv/bin/python tests/test_blender.py   (skips if Blender isn't installed)"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from features import ffmpeg, full_timeline  # noqa: E402  (also puts the repo on sys.path)

from editor import Timeline  # noqa: E402
from editor.export import export  # noqa: E402

BLENDER = shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
W, H = 1920, 1080


def render(tl, tmp):
    script = export(tl, "blender", tmp)[0]
    out = tmp / f"{tl.name}.mp4"
    r = subprocess.run([BLENDER, "-b", "--python", str(script), "--", "--render", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and out.exists(), (r.stdout + r.stderr)[-2000:]
    assert "Traceback" not in r.stdout + r.stderr, (r.stdout + r.stderr)[-2000:]
    return out


def frame(mp4, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert len(raw) == W * H * 3, f"no frame at t={t}"
    return raw


def px(raw, fx, fy):
    """Mean RGB of a 5x5 patch at fractional position (fx, fy)."""
    x, y = int(fx * W), int(fy * H)
    patch = [raw[((y + dy) * W + x + dx) * 3:][:3] for dy in range(-2, 3) for dx in range(-2, 3)]
    return tuple(sum(p[i] for p in patch) / len(patch) for i in range(3))


def count(raw, test, y0=0.75, y1=0.97):
    """Pixels in a horizontal band (default: the title band) satisfying test(r, g, b)."""
    n = 0
    for y in range(int(y0 * H), int(y1 * H), 3):
        row = raw[y * W * 3:(y + 1) * W * 3]
        n += sum(1 for i in range(0, len(row), 9) if test(row[i], row[i + 1], row[i + 2]))
    return n


def near(rgb, want, tol=30):
    return all(abs(a - b) <= tol for a, b in zip(rgb, want)), f"got {tuple(round(v) for v in rgb)}, want {want} +-{tol}"


def check(rgb, want, tol=30):
    ok, msg = near(rgb, want, tol)
    assert ok, msg


def duration(mp4):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                                capture_output=True, text=True).stdout)


def has_stream(mp4, kind):
    return kind in subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                   str(mp4)], capture_output=True, text=True).stdout


def peak_db(mp4, t0, t1):
    out = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(t0), "-t", str(t1 - t0), "-i", str(mp4), "-vn",
                          "-af", "astats=metadata=0", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(re.findall(r"Peak level dB: (-?[\d.]+|-inf)", out.replace("-inf", "-200"))[-1])


def test_full_timeline(tmp):
    """Every feature at once: duration, streams, and what the picture looks like at known times."""
    tl = full_timeline(tmp)
    mp4 = render(tl, tmp)
    assert abs(duration(mp4) - tl.duration) < 1 / tl.fps + 0.02, duration(mp4)
    assert has_stream(mp4, "video") and has_stream(mp4, "audio")

    check(px(frame(mp4, 0.0), .5, .4), (0, 0, 0), 25)               # fade_in 0.5 s starts from black
    mid = px(frame(mp4, 0.25), .5, .4)
    assert 40 < mid[0] < 200 and mid[2] < 40, f"half-faded red expected, got {mid}"
    check(px(frame(mp4, 0.8), .5, .4), (255, 0, 0), 40)             # fully red (also zoomed 1.5x by the click zoom)
    check(px(frame(mp4, 2.0), .5, .4), (255, 0, 0), 40)             # overlay (red @50%) over red is still red
    x = px(frame(mp4, 3.5), .5, .4)                                  # middle of the 1 s crossfade red -> blue
    assert 90 < x[0] < 200 and 90 < x[2] < 200 and x[1] < 40, f"red/blue blend expected, got {x}"
    check(px(frame(mp4, 5.0), .5, .4), (0, 0, 255), 40)             # blue
    still = frame(mp4, 8.0)
    check(px(still, .5, .4), (0, 128, 0), 40)                       # green still, centre
    check(px(still, .05, .4), (0, 0, 0), 15)                        # 4:3 still is letterboxed, not stretched
    check(px(frame(mp4, 10.0), .5, .4), (255, 0, 0), 40)            # 2x speed red clip

    # titles: yellow "Hello" while 1-3 s (after its 0.5 s fade), white "World" 5-7 s, nothing at 4 s
    yellow = lambda r, g, b: r > 200 and g > 200 and b < 90
    white = lambda r, g, b: r > 200 and g > 200 and b > 200
    assert count(frame(mp4, 2.0), yellow) > 100, "yellow title missing at 2 s"
    assert count(frame(mp4, 4.0), yellow) == 0, "title still showing at 4 s"
    assert count(frame(mp4, 6.0), white) > 100, "white title missing at 6 s"
    assert count(frame(mp4, 1.1), yellow) < count(frame(mp4, 2.0), yellow), "title should still be fading in at 1.1 s"


def ramp(tmp, name="ramp.mp4", fps=30):
    """10 s clip whose red level is 25*t, so the pixel value says which source second is on screen."""
    ffmpeg("-f", "lavfi", "-i", f"color=c=black:s=320x180:r={fps}:d=10", "-vf",
           "format=gbrp,geq=g='0':b='0':r='min(255,25*T)'", "-pix_fmt", "yuv420p", str(tmp / name))
    return tmp / name


def source_second(rgb):
    return rgb[0] / 25


def test_trim_and_speed(tmp):
    r = ramp(tmp)
    tl = Timeline("trim")
    tl.add_clip(r, dur=2, src=4)                    # source 4-6 s at 0-2 s
    tl.add_clip(r, dur=2, src=2, speed=2)           # source 2-6 s at 2-4 s
    mp4 = render(tl, tmp)
    for t, want in [(0.05, 4.05), (1.0, 5.0), (1.9, 5.9), (2.05, 2.1), (3.0, 4.0), (3.9, 5.8)]:
        got = source_second(px(frame(mp4, t), .5, .5))
        assert abs(got - want) < 0.45, f"t={t}: showing source {got:.2f}s, want {want}s"


def test_media_fps_differs_from_timeline_fps(tmp):
    r = ramp(tmp, "ramp30.mp4", fps=30)
    tl = Timeline("fps24", fps=24)
    tl.add_clip(r, dur=2, src=4)
    mp4 = render(tl, tmp)
    for t, want in [(0.05, 4.05), (1.0, 5.0), (1.9, 5.9)]:
        got = source_second(px(frame(mp4, t), .5, .5))
        assert abs(got - want) < 0.45, f"t={t}: showing source {got:.2f}s, want {want}s"
    assert abs(duration(mp4) - 2) < 0.1, duration(mp4)


def test_opacity(tmp):
    ffmpeg("-f", "lavfi", "-i", "color=blue:s=1280x720:r=30:d=3", "-pix_fmt", "yuv420p", str(tmp / "b.mp4"))
    ffmpeg("-f", "lavfi", "-i", "color=red:s=1280x720:r=30:d=3", "-pix_fmt", "yuv420p", str(tmp / "r.mp4"))
    tl = Timeline("opacity")
    tl.add_clip(tmp / "b.mp4", dur=3)
    tl.add_clip(tmp / "r.mp4", dur=3, start=0, track=1, opacity=0.5)
    check(px(frame(render(tl, tmp), 1.5), .5, .5), (127, 0, 127), 30)


def test_zoom(tmp):
    ffmpeg("-f", "lavfi", "-i", "color=red:s=640x1080:r=30:d=3", "-f", "lavfi", "-i", "color=green:s=640x1080:r=30:d=3",
           "-f", "lavfi", "-i", "color=blue:s=640x1080:r=30:d=3", "-filter_complex", "hstack=3", "-pix_fmt", "yuv420p",
           str(tmp / "bands.mp4"))
    tl = Timeline("zoom")
    flat = tl.add_clip(tmp / "bands.mp4", dur=3)
    zoomed = tl.add_clip(tmp / "bands.mp4", dur=3)
    zoomed.zoom = [(0.0, 1.0), (1.0, 2.0), (3.0, 2.0)]
    mp4 = render(tl, tmp)
    check(px(frame(mp4, 0.5), .30, .5), (255, 0, 0), 40)              # unzoomed: left band is red
    check(px(frame(mp4, 3.0 + 2.0), .30, .5), (0, 128, 0), 40)        # 2x about the centre: that spot is now green
    check(px(frame(mp4, 3.0 + 2.0), .05, .5), (255, 0, 0), 40)        # and the far left is still red, not black
    assert flat.zoom == []


def test_audio_volume_and_fades(tmp):
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=8", str(tmp / "tone.mp3"))
    quiet, loud = Timeline("quiet"), Timeline("loud")
    quiet.add_audio(tmp / "tone.mp3", dur=8, volume=0.5, fade_in=1, fade_out=2)
    loud.add_audio(tmp / "tone.mp3", dur=8, volume=1.0)
    q, l = render(quiet, tmp), render(loud, tmp)
    steady_q, steady_l = peak_db(q, 2.5, 5.0), peak_db(l, 2.5, 5.0)
    assert abs((steady_l - steady_q) - 6.0) < 1.5, f"volume 0.5 should be ~6 dB down: {steady_l} vs {steady_q}"
    assert peak_db(q, 0.0, 0.15) < steady_q - 12, "fade-in should start near silence"
    assert peak_db(q, 7.85, 8.0) < steady_q - 12, "fade-out should end near silence"
    assert -9 < peak_db(q, 0.35, 0.5) - steady_q < -3, "fade-in is halfway at ~0.5 s"
    assert -9 < peak_db(q, 7.0, 7.1) - steady_q < -3, "fade-out is halfway at ~7 s"


if __name__ == "__main__":
    if not Path(BLENDER).exists():
        sys.exit("skipped: Blender not installed (brew install --cask blender)")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(Path(tempfile.mkdtemp()))
            print("ok", name)

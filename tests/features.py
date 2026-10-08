"""One timeline that exercises every feature in editor.timeline.FEATURES. Every exporter is tested against it."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from editor import Timeline
from editor.zoom import apply_click_zoom


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def media(tmp):
    """red.mp4, blue.mp4 (10 s, 1280x720 with tone), music.mp3 (8 s), still.png."""
    for name, color in [("red", "red"), ("blue", "blue")]:
        ffmpeg("-f", "lavfi", "-i", f"color={color}:s=1280x720:r=30:d=10", "-f", "lavfi",
               "-i", "sine=frequency=440:duration=10", "-shortest", "-pix_fmt", "yuv420p", str(tmp / f"{name}.mp4"))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=8", str(tmp / "music.mp3"))
    ffmpeg("-f", "lavfi", "-i", "color=green:s=800x600", "-frames:v", "1", str(tmp / "still.png"))
    return {n: tmp / f for n, f in [("red", "red.mp4"), ("blue", "blue.mp4"), ("music", "music.mp3"), ("still", "still.png")]}


def full_timeline(tmp):
    """Timeline (all times in s):
      V0: red 0-4 (src 2-6, zoomed, fades in 0.5)
          blue 3-7 (src 5-9): crossfade 1 -> overlaps red 3-4
          still 7-9 (a png)
          red 9-11 at speed 2 (consumes 4 s of source from src 0)
      V1: red overlay 1-3, opacity 0.5
      A0: music 0-8, volume 0.5, fade in 1, fade out 2
      titles: 'Hello' 1-3 (fade 0.5, yellow), 'World' 5-7
    """
    m = media(tmp)
    tl = Timeline("full")
    first = tl.add_clip(m["red"], dur=4, src=2, fade_in=0.5)
    tl.add_clip(m["blue"], dur=4, src=5, crossfade=1)
    tl.add_clip(m["still"], dur=2)
    tl.add_clip(m["red"], dur=2, speed=2)
    tl.add_clip(m["red"], dur=2, start=1, track=1, opacity=0.5)
    tl.add_audio(m["music"], dur=8, volume=0.5, fade_in=1, fade_out=2)
    tl.add_title("Hello", 1, 2, fade=0.5, color="#ffff00")
    tl.add_title("World", 5, 2)
    apply_click_zoom(first, [1.0])
    return tl

"""Blender script: `blender -b --python Name.blender.py` builds the edit; add `-- --render out.mp4` to render it.

Written against Blender 5.2 (verified by a real headless render, see tests/test_blender.py). It also adapts to the
pre-5.0 names (`sequences`, `new_effect(..., frame_end)`) but that path is untested.
"""
import json
from dataclasses import asdict
from pathlib import Path

from ..timeline import FEATURES, probe

SUPPORTS = set(FEATURES)

BUILDER = r'''
import sys
import bpy

tl = json.loads(TIMELINE)
fps = tl["fps"]
F = lambda s: round(s * fps)          # seconds -> frame count
T = lambda s: F(s) + 1                # seconds -> timeline frame (Blender starts at frame 1)

scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = tl["width"], tl["height"]
scene.render.resolution_percentage = 100
scene.render.fps, scene.render.fps_base = fps, 1
scene.view_settings.view_transform = "Standard"      # the default (AgX/Filmic) tone-maps colours; an edit should come out as shot
scene.view_settings.look = "None"
if scene.sequence_editor is None:
    scene.sequence_editor_create()
se = scene.sequence_editor
strips = se.strips if hasattr(se, "strips") else se.sequences   # `strips` from Blender 5.0, `sequences` before


def new_effect(name, kind, channel, start, length, **inputs):
    try:
        return strips.new_effect(name, kind, channel, start, length=length, **inputs)
    except TypeError:                                       # Blender < 5: frame_end positional, seq1/seq2 inputs
        old = {k.replace("input", "seq"): v for k, v in inputs.items()}
        return strips.new_effect(name, kind, channel, start, start + length, **old)


def keys(strip, prop, points):
    """points: [(timeline frame, value)] on a strip property such as 'blend_alpha' or 'transform.scale_x'."""
    obj = strip
    *path, leaf = prop.split(".")
    for p in path:
        obj = getattr(obj, p)
    for frame, value in points:
        setattr(obj, leaf, value)
        obj.keyframe_insert(leaf, frame=frame)      # on the nested struct: strip.keyframe_insert("a.b") can't resolve it


def fade_points(start, dur, base, fade_in, fade_out):
    """Level 0 -> base over fade_in, base -> 0 over fade_out; None if there is nothing to animate."""
    if not (fade_in or fade_out):
        return None
    pts = [(start, 0 if fade_in else base)]
    if fade_in:
        pts.append((start + F(fade_in), base))
    if fade_out:
        pts += [(start + dur - F(fade_out), base), (start + dur, 0)]
    return pts


START_PROP = "content_start" if "content_start" in bpy.types.Strip.bl_rna.properties else "frame_start"
FAR = -1_000_000     # Blender 5.2: retiming keys are initialised from the strip with the smallest start, not from the strip
                     # they are called on (wrong keys, random crashes). So a strip is retimed far to the left, where it
                     # is its own smallest, then moved into place.


def span(strip):
    return (strip.left_handle, strip.right_handle) if hasattr(strip, "left_handle") else (strip.frame_final_start, strip.frame_final_end)


def set_span(strip, start, end):
    if hasattr(strip, "left_handle"):               # frame_final_* is deprecated from Blender 5.x
        strip.left_handle, strip.right_handle = start, end
    else:
        strip.frame_final_start, strip.frame_final_end = start, end


def retime(strip, speed):
    """Give a movie/sound strip retiming keys, and change its speed (one extra key in the middle, then scale both key
    positions from the start). Every movie/sound strip is primed even at speed 1: Blender 5.2 initialises new keys from
    the first strip that has none yet, so all earlier strips must already have some (see the build order below).
    A key can't cross its neighbour, so compress moves the middle key first and stretch moves the end first."""
    a, b = span(strip)
    se.active_strip = strip
    strip.retiming_keys.add(timeline_frame=(a + b) // 2)
    if abs(speed - 1) < 1e-6:
        return
    mid = strip.retiming_keys[1].timeline_frame
    new_mid, new_end = a + max(round((mid - a) / speed), 1), a + max(round((b - a) / speed), 2)
    for index, frame in ([(1, new_mid), (2, new_end)] if speed > 1 else [(2, new_end), (1, new_mid)]):
        strip.retiming_keys[index].timeline_frame = frame      # fetch fresh: Blender reallocates the keys when one moves


SCRATCH = 128      # strips are built here, because an untrimmed strip overlapping a neighbour makes Blender shove it


def place(maker, name, path, channel, start, src_seconds, dur, speed=1.0, fit_frame=False, retimable=True):
    """Create a strip so `src_seconds` into the file plays at timeline frame `start`, shown for `dur` frames at `speed`."""
    strip = fit(maker, name, path, SCRATCH, FAR) if fit_frame else maker(name, path, SCRATCH, FAR)
    media_fps = getattr(strip, "fps", 0) or fps         # Blender plays movie frames 1:1, so a 30 fps file in a 24 fps edit
    speed *= media_fps / fps                            # must be retimed by the ratio to run in real time (sound is already in seconds)
    if retimable:
        retime(strip, speed)                            # while untrimmed: the key frames are plain timeline frames
    setattr(strip, START_PROP, start - round(src_seconds * media_fps / speed))
    set_span(strip, start, start + dur)
    strip.channel = channel
    return strip


def fit(maker, *args):
    try:
        return maker(*args, fit_method="FIT")               # scale to fit the frame, like every other editor
    except TypeError:
        return maker(*args)


# ---- channel plan: video tracks (3 channels each: two alternating lanes + crossfade effect), titles, then sound
vtracks = sorted({c["track"] for c in tl["clips"] if c["kind"] == "video"})
title_base = 1 + 3 * len(vtracks)
lanes = []                                                  # overlapping titles need their own channel
for t in sorted(tl["titles"], key=lambda t: t["start"]):
    lane = next((l for l in lanes if l[-1]["start"] + l[-1]["dur"] <= t["start"]), None)
    lanes.append([t]) if lane is None else lane.append(t)
sound_base = title_base + len(lanes) + 1
alists = [("v", tr) for tr in vtracks] + [("a", tr) for tr in sorted({c["track"] for c in tl["clips"] if c["kind"] == "audio"})]

def sound_channel(kind, track, parity):
    return sound_base + 2 * alists.index(("v" if kind == "video" else "a", track)) + parity


groups = [(i, kind, sorted((c for c in tl["clips"] if c["kind"] == ("video" if kind == "v" else "audio") and c["track"] == track),
                           key=lambda c: c["start"])) for i, (kind, track) in enumerate(alists)]
made = {}


def look(strip, c, start, dur):
    """Opacity, fades and zoom of a picture strip."""
    strip.blend_type = "ALPHA_OVER"
    pts = fade_points(start, dur, c["opacity"], c["fade_in"], c["fade_out"])
    if pts:
        keys(strip, "blend_alpha", pts)
    else:
        strip.blend_alpha = c["opacity"]
    base = strip.transform.scale_x                          # the "fit" scale; zoom multiplies it
    for sec, scale in c["zoom"]:
        keys(strip, "transform.scale_x", [(start + F(sec), base * scale)])
        keys(strip, "transform.scale_y", [(start + F(sec), base * scale)])


# Build order matters (Blender 5.2 retiming bug, see retime): movies and sound first, each primed with retiming keys
# before the next is created; only then stills, crossfades and titles, which can never hold keys.
for i, kind, members in groups:
    for n, c in enumerate(members):
        start, dur = T(c["start"]), F(c["dur"])
        if kind == "v" and not c["is_image"]:
            made[i, n] = place(strips.new_movie, f"v{n}", c["path"], 1 + 3 * i + n % 2, start, c["src"], dur, c["speed"], fit_frame=True)
            look(made[i, n], c, start, dur)
        if c["has_audio"] and not c["is_image"]:
            nxt = members[n + 1] if n + 1 < len(members) else None
            fade_in = max(c["fade_in"], c["crossfade"])      # sound crosses over with a linear fade
            fade_out = max(c["fade_out"], nxt["crossfade"] if nxt else 0)
            snd = place(strips.new_sound, f"s{n}", c["path"], sound_channel(c["kind"], c["track"], n % 2), start, c["src"], dur, c["speed"])
            pts = fade_points(start, dur, c["volume"], fade_in, fade_out)
            if pts:
                keys(snd, "volume", pts)
            else:
                snd.volume = c["volume"]
for i, kind, members in groups:
    for n, c in enumerate(members):
        if c["is_image"]:
            start, dur = T(c["start"]), F(c["dur"])
            made[i, n] = place(strips.new_image, f"v{n}", c["path"], 1 + 3 * i + n % 2, start, 0, dur, fit_frame=True, retimable=False)
            look(made[i, n], c, start, dur)
for i, kind, members in groups:
    for n, c in enumerate(members):
        if kind == "v" and n and c["crossfade"]:
            new_effect("xf", "CROSS", 1 + 3 * i + 2, T(c["start"]), F(c["crossfade"]), input1=made[i, n - 1], input2=made[i, n])

for i, lane in enumerate(lanes):
    for t in lane:
        start, dur = T(t["start"]), F(t["dur"])
        s = new_effect(f"t{i}", "TEXT", title_base + i, start, dur)
        s.text, s.font_size = t["text"], t["size"]
        s.color = [int(t["color"][j:j + 2], 16) / 255 for j in (1, 3, 5)] + [1.0]
        s.location = (0.5, (t["y"] + 1) / 2)                # (0,0) bottom-left .. (1,1) top-right
        if hasattr(s, "anchor_x"):
            s.anchor_x, s.anchor_y = "CENTER", "CENTER"
        else:
            s.align_x = "CENTER"
        pts = fade_points(start, dur, 1.0, t["fade"], t["fade"])
        if pts:
            keys(s, "blend_alpha", pts)

scene.frame_start, scene.frame_end = 1, max(F(tl["duration"]), 1)
if "--render" in sys.argv:
    scene.render.filepath = sys.argv[sys.argv.index("--render") + 1]
    if hasattr(scene.render.image_settings, "media_type"):      # Blender 5: pick video before FFMPEG is offered
        scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.audio_codec = "AAC"
    scene.render.ffmpeg.audio_channels = "STEREO"
    scene.render.ffmpeg.audio_mixrate = 48000
    bpy.ops.render.render(animation=True)
'''


def export(tl, out_dir):
    data = asdict(tl) | {"duration": tl.duration}
    for c in data["clips"]:                       # bake what the script would otherwise have to guess
        info = probe(c["path"])
        c["has_audio"], c["is_image"] = info["has_audio"], info["is_image"]
    path = Path(out_dir) / f"{tl.name}.blender.py"
    path.write_text(f"import json\nTIMELINE = {json.dumps(json.dumps(data))}\n{BUILDER}")
    return [path]

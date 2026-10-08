"""Build one timeline from generated media, export to every editor, check the output is well-formed and right.
Run: python tests/test_exports.py   (needs ffmpeg; the CapCut check needs pyJianYingDraft and is skipped without it)"""
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent.parent))
from editor import Timeline
from editor.export import export
from editor.zoom import apply_click_zoom


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def build(tmp):
    a, b, music = tmp / "a.mp4", tmp / "b.mp4", tmp / "music.mp3"
    for f, color in [(a, "red"), (b, "blue")]:
        ffmpeg("-f", "lavfi", "-i", f"color={color}:s=1280x720:r=30:d=10", "-f", "lavfi",
               "-i", "sine=frequency=440:duration=10", "-shortest", "-pix_fmt", "yuv420p", str(f))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=8", str(music))

    tl = Timeline("demo")
    first = tl.add_clip(a, dur=4, src=2)                  # a.mp4 seconds 2-6 at 0-4
    tl.add_clip(b, dur=3, src=5)                          # then b.mp4 seconds 5-8 at 4-7
    tl.add_clip(a, dur=2, src=0, start=1, track=1)        # overlay on track 1
    tl.add_audio(music, dur=7, volume=0.5)
    tl.add_title("Hello", 1, 2)
    tl.add_title("World", 4, 2)
    apply_click_zoom(first, [1.0])
    return tl


def test_every_exporter_supports_every_feature():
    import importlib
    from editor.export import TARGETS
    from editor.timeline import FEATURES
    for module in sorted(set(TARGETS.values())):
        supports = importlib.import_module(f"editor.export.{module}").SUPPORTS
        assert supports == set(FEATURES), (module, set(FEATURES) - supports)


def test_timeline_math(tl):
    assert [(c.start, c.dur) for c in tl.clips[:2]] == [(0.0, 4), (4.0, 3)], "clips chain end to start"
    assert tl.duration == 7
    assert "00:00:01,000 --> 00:00:03,000\nHello" in tl.srt()


def test_json_roundtrip(tl, tmp):
    tl.save(tmp / "t.json")
    again = Timeline.load(tmp / "t.json")
    assert again == tl


def test_fcpxml(tl, tmp):
    xml = ET.parse(export(tl, "fcp", tmp)[0]).getroot()
    spine = xml.find(".//spine")
    clips = spine.findall("asset-clip")
    assert [c.get("offset") for c in clips] == ["0/30s", "120/30s"]
    assert clips[0].get("start") == "60/30s" and clips[0].get("duration") == "120/30s"   # trim = start/duration
    assert len(clips[0].findall(".//keyframe")) == 4, "zoom keyframes"
    assert spine.find("gap") is None, "main track covers the whole timeline"
    lanes = sorted(e.get("lane") for e in xml.iter() if e.get("lane"))
    assert lanes == ["-1", "1", "2", "2"], lanes          # overlay, music, two titles
    assert xml.find(".//adjust-volume").get("amount") == "-6.0dB"


def test_fcpxml_gap_holds_connected_clips(tl, tmp):
    late = Timeline("late")
    late.add_clip(tl.clips[0].path, dur=2, start=2)       # nothing before 2s on the main track
    late.add_title("Early", 0.5, 1)
    spine = ET.parse(export(late, "fcp", tmp)[0]).getroot().find(".//spine")
    gap = spine.find("gap")
    assert (gap.get("offset"), gap.get("duration")) == ("0/30s", "60/30s")
    assert gap.find("title").get("offset") == "108015/30s", "1h gap start + 0.5s"   # 3600*30 + 15


def test_premiere(tl, tmp):
    paths = export(tl, "premiere", tmp)
    xml = ET.parse(paths[0]).getroot()
    items = xml.findall("./sequence/media/video/track")[0].findall("clipitem")
    assert [(i.findtext("start"), i.findtext("end"), i.findtext("in"), i.findtext("out")) for i in items] == \
        [("0", "120", "60", "180"), ("120", "210", "150", "240")]
    assert paths[1].suffix == ".srt"
    assert xml.findall(".//file[@id='file-1']")[0].find("pathurl") is not None


def test_mlt(tl, tmp):
    xml = ET.parse(export(tl, "kdenlive", tmp)[0]).getroot()
    v0 = xml.find("playlist[@id='v0_0']")
    assert [(e.get("in"), e.get("out")) for e in v0.findall("entry")] == [("60", "179"), ("150", "239")]
    ids = {p.get("id") for p in xml.findall("producer")}
    assert all(e.get("producer") in ids for e in xml.iter("entry")), "every entry has a producer"
    assert all(tr.get("producer") in {p.get("id") for p in xml.findall("playlist")}
               for tr in xml.iter("track")), "every track has a playlist"
    assert len(xml.findall(".//filter[@mlt_service='dynamictext']")) == 2


def test_blender_and_resolve_scripts_parse(tl, tmp):
    for target in ("blender", "resolve"):
        for p in export(tl, target, tmp):
            if p.suffix == ".py":
                ast.parse(p.read_text())
    embedded = ast.parse((tmp / "demo.blender.py").read_text()).body[1].value.value
    assert json.loads(embedded)["duration"] == 7


def test_capcut(tl, tmp):
    try:
        import pyJianYingDraft  # noqa: F401
    except ImportError:
        print("  skipped (pyJianYingDraft not installed)")
        return
    path = export(tl, "capcut", tmp / "drafts")[0]
    tracks = json.loads(path.read_text())["tracks"]
    kinds = sorted(t["type"] for t in tracks)
    assert kinds == ["audio", "text", "video", "video"], kinds
    main = next(t for t in tracks if t["type"] == "video")["segments"]
    assert main[0]["source_timerange"] == {"start": 2_000_000, "duration": 4_000_000}


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp())
    tl = build(tmp)
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            args = fn.__code__.co_varnames[:fn.__code__.co_argcount]
            fn(*[{"tl": tl, "tmp": tmp}[a] for a in args])
            print("ok", name)

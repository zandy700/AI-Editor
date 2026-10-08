"""FCPXML exporter vs the shared full-feature timeline. Run: .venv/bin/python tests/test_fcpxml.py"""
import ast
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from features import full_timeline

from editor.export import fcpxml, resolve
from editor.export import export
from editor.timeline import FEATURES

FPS = 30


def sec(s):
    """'105/30s' -> Fraction seconds."""
    n, _, d = s[:-1].partition("/")
    return Fraction(int(n), int(d or 1))


def source_time(el, tl_time):
    """Source-media time shown by spine/connected item `el` at timeline time (works outside its range = handles)."""
    local = sec(el.get("start")) + (tl_time - sec(el.get("offset")))
    pts = [(sec(p.get("time")), sec(p.get("value"))) for p in el.findall("timeMap/timept")]
    if not pts:
        return local
    (t0, v0), (t1, v1) = pts[0], pts[-1]
    return v0 + (local - t0) * (v1 - v0) / (t1 - t0)


def build():
    tmp = Path(tempfile.mkdtemp())
    tl = full_timeline(tmp)
    path = export(tl, "fcp", tmp)[0]
    return tl, tmp, path, ET.parse(path).getroot()


def test_declares_every_feature():
    assert fcpxml.SUPPORTS == set(FEATURES) == resolve.SUPPORTS


def test_wellformed_and_refs_resolve(path, xml):
    if shutil.which("xmllint"):
        subprocess.run(["xmllint", "--noout", str(path)], check=True)
    ids = {e.get("id") for e in xml.find("resources")}
    refs = [e.get("ref") for e in xml.iter() if e.get("ref") and e.tag != "text-style"]   # text-style -> text-style-def
    refs += [e.get("format") for e in xml.iter("asset") if e.get("format")]                # audio assets have no format
    assert refs and all(r in ids for r in refs), set(refs) - ids
    style_ids = {e.get("id") for e in xml.iter("text-style-def")}
    assert all(e.get("ref") in style_ids for e in xml.iter("text-style") if e.get("ref"))
    assert len(ids) == len(list(xml.find("resources"))), "duplicate resource ids"


def test_times_are_frame_aligned(xml):
    for e in xml.iter():
        for k in ("offset", "start", "duration", "time", "value", "frameDuration"):
            v = e.get(k, "")
            if k == "value" and not v.endswith("s"):
                continue
            if v.endswith("s"):
                assert re.fullmatch(r"\d+/\d+s|\d+s", v), (e.tag, k, v)
                if k != "frameDuration":
                    assert (sec(v) * FPS).denominator == 1, (e.tag, k, v)


def test_main_track_timing_and_crossfade(xml):
    spine = xml.find(".//spine")
    kinds = [e.tag for e in spine]
    assert kinds == ["asset-clip", "transition", "asset-clip", "video", "asset-clip"], kinds
    red, tr, blue, still, fast = list(spine)
    # clips overlap by 1s at 3-4s -> centred dissolve at 90 frames, cut point P=105
    assert (tr.get("offset"), tr.get("duration")) == ("90/30s", "30/30s")
    assert (red.get("offset"), red.get("duration")) == ("0/30s", "105/30s")
    assert (blue.get("offset"), blue.get("start"), blue.get("duration")) == ("105/30s", "165/30s", "105/30s")
    # picture/source mapping: the dissolve is filled from both clips' handles
    assert source_time(red, Fraction(3, 1)) == 5                      # red src 2 + 3
    assert source_time(red, Fraction(7, 2)) == Fraction(11, 2)        # in the handle past the cut
    assert source_time(blue, Fraction(7, 2)) == Fraction(11, 2)       # blue src 5 + 0.5, before its cut
    assert source_time(blue, Fraction(5, 1)) == 7
    # still: a <video> on an image asset, 2s long, placed at 7s
    assert (still.get("offset"), still.get("duration")) == ("210/30s", "60/30s")
    # speed 2: 1s into the clip is 2s into the source, via timeMap
    assert fast.find("timeMap") is not None and fast.get("offset") == "270/30s"
    assert source_time(fast, Fraction(10, 1)) == 2
    assert source_time(fast, Fraction(11, 1)) == 4                    # dur 2s consumes 4s of source


def test_features_on_clips(xml):
    spine = xml.find(".//spine")
    red = spine.find("asset-clip")
    kf = red.findall("adjust-blend/param/keyframeAnimation/keyframe")
    assert [(k.get("time"), k.get("value")) for k in kf] == [("60/30s", "0"), ("75/30s", "1")], "fade in 0.5s"
    assert len(red.findall("adjust-transform//keyframe")) == 4, "zoom"
    # overlay: connected on lane 1 to the spine clip that covers 1s, half opacity
    over = next(e for e in red.iter("asset-clip") if e.get("lane") == "1")
    assert over.find("adjust-blend").get("amount") == "0.5"
    assert over.get("offset") == "90/30s"                              # red local start 60 + 1s*30
    # music: connected below, -6 dB, 1s in / 2s out
    music = next(e for e in xml.iter("asset-clip") if e.get("lane") == "-1")
    vol = music.find("adjust-volume")
    assert vol.get("amount") == "-6.0dB"
    assert vol.find("param/fadeIn").get("duration") == "30/30s"
    assert vol.find("param/fadeOut").get("duration") == "60/30s"


def test_titles(xml):
    titles = sorted(xml.iter("title"), key=lambda e: sec(e.get("offset")))
    assert [t.findtext("text/text-style") for t in titles] == ["Hello", "World"]
    hello = titles[0]
    assert [k.get("value") for k in hello.findall("adjust-blend//keyframe")] == ["0", "1", "1", "0"]
    assert hello.find("text-style-def/text-style").get("fontColor") == "1 1 0 1"
    assert titles[1].find("adjust-blend") is None and titles[1].find("text-style-def/text-style").get("fontColor") == "1 1 1 1"


def test_resolve_script_parses(tl, tmp):
    for p in resolve.export(tl, tmp):
        if p.suffix == ".py":
            ast.parse(p.read_text())


if __name__ == "__main__":
    tl, tmp, path, xml = build()
    test_declares_every_feature(); print("ok declares_every_feature")
    test_wellformed_and_refs_resolve(path, xml); print("ok wellformed_and_refs_resolve")
    test_times_are_frame_aligned(xml); print("ok times_are_frame_aligned")
    test_main_track_timing_and_crossfade(xml); print("ok main_track_timing_and_crossfade")
    test_features_on_clips(xml); print("ok features_on_clips")
    test_titles(xml); print("ok titles")
    test_resolve_script_parses(tl, tmp); print("ok resolve_script_parses")

"""Premiere (xmeml) exporter against the shared full-feature timeline: well-formed, ids/files consistent,
and the timeline math (what source frame plays at a given timeline frame) read back from the XML.
Run: .venv/bin/python tests/test_premiere.py"""
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from features import full_timeline
from editor.export import premiere
from editor.timeline import FEATURES


def load(tmp):
    tl = full_timeline(tmp)
    xml, srt = premiere.export(tl, tmp)
    return tl, xml, ET.parse(xml).getroot(), srt


def filt(ci, name):
    return next((e for e in ci.findall("./filter/effect") if e.findtext("name") == name), None)


def param(eff, pid):
    p = next(p for p in eff.findall("parameter") if p.findtext("parameterid") == pid)
    return p.findtext("value"), [(int(k.findtext("when")), float(k.findtext("value"))) for k in p.findall("keyframe")]


def source_frame(track, t):
    """Source frame shown at timeline frame t on a video/audio track, honouring speed; None if nothing plays."""
    for ci in track.findall("clipitem"):
        s, e = int(ci.findtext("start")), int(ci.findtext("end"))
        if s <= t < e:
            remap = filt(ci, "Time Remap")
            speed = float(param(remap, "speed")[0]) / 100 if remap is not None else 1
            return int(ci.findtext("in")) + round((t - s) * speed)


def test_supports_every_feature():
    assert premiere.SUPPORTS == set(FEATURES)


def test_well_formed_and_consistent(tmp):
    tl, xml, root, srt = load(tmp)
    subprocess.run(["xmllint", "--noout", str(xml)], check=True)
    ids = [e.get("id") for e in root.iter() if e.tag in ("clipitem", "generatoritem")]
    assert len(ids) == len(set(ids)), "ids unique"
    defined = set()
    for fe in root.iter("file"):                      # document order: first use must carry the definition
        if fe.find("pathurl") is not None:
            defined.add(fe.get("id"))
        else:
            assert fe.get("id") in defined, f"file {fe.get('id')} used before it is defined"
    for tag in ("start", "end", "in", "out"):
        for e in root.iter(tag):
            assert e.text.isdigit(), f"<{tag}> not an integer frame: {e.text}"
    refs = {l.findtext("linkclipref") for l in root.iter("link")}
    assert refs <= set(ids)
    assert srt.read_text().count("-->") == 2


def test_timeline_math(tmp):
    tl, xml, root, srt = load(tmp)
    v0, v1 = root.findall("./sequence/media/video/track")[:2]
    # red 0-4 s, src 2 s: frame 30 (1 s) -> source 90 (3 s)
    assert source_frame(v0, 30) == 90
    # dissolve 3-4 s (frames 90-120) is centred on the cut at frame 105
    assert source_frame(v0, 100) == 60 + 100                       # still red: src 2 s + 3.33 s
    assert source_frame(v0, 110) == 150 + (110 - 90)               # blue: src 5 s + 20 frames in from its own start
    # still 7-9 s
    still = [ci for ci in v0.findall("clipitem") if ci.findtext("stillframe") == "TRUE"]
    assert len(still) == 1 and (still[0].findtext("start"), still[0].findtext("end")) == ("210", "270")
    # red at 2x, 9-11 s: half a second in (frame 285) is 30 source frames in
    assert source_frame(v0, 285) == 0 + 30
    assert source_frame(v0, 269 + 1) == 0, "sped clip starts at 9 s"
    # overlay lives on its own track, 1-3 s
    assert source_frame(v1, 45) == 0 + 15 and source_frame(v1, 100) is None


def test_crossfade_transitions(tmp):
    tl, xml, root, srt = load(tmp)
    v0 = root.findall("./sequence/media/video/track")[0]
    (t,) = v0.findall("transitionitem")
    assert (t.findtext("start"), t.findtext("end"), t.findtext("alignment")) == ("90", "120", "center")
    assert t.findtext("effect/name") == "Cross Dissolve"
    names = [e.tag for e in v0]
    assert names.index("transitionitem") == 1, "transition sits between the two clipitems"
    a, b = v0.findall("clipitem")[:2]
    assert a.findtext("end") == b.findtext("start") == "105"      # clips are adjacent at the cut
    audio_t = [t for tr in root.findall("./sequence/media/audio/track") for t in tr.findall("transitionitem")]
    assert [x.findtext("effect/mediatype") for x in audio_t] == ["audio"], "sound crossfades too"


def test_opacity_fades_volume_speed(tmp):
    tl, xml, root, srt = load(tmp)
    v0, v1 = root.findall("./sequence/media/video/track")[:2]
    red = v0.findall("clipitem")[0]
    # fade-in over 0.5 s, then full; the clip ends at the crossfade cut (frame 105) so there is no fade-out
    assert param(filt(red, "Opacity"), "opacity")[1] == [(0, 0.0), (15, 100.0), (105, 100.0)]
    assert param(filt(v1.find("clipitem"), "Opacity"), "opacity")[0] == "50"
    sped = v0.findall("clipitem")[-1]
    assert param(filt(sped, "Time Remap"), "speed")[0] == "200"
    assert (sped.findtext("in"), sped.findtext("out")) == ("0", "120"), "2x consumes twice the timeline length"
    music = next(ci for tr in root.findall("./sequence/media/audio/track") for ci in tr.findall("clipitem")
                 if ci.findtext("name") == "music")
    level = param(filt(music, "Audio Levels"), "level")
    assert level[0] == "0.5"
    assert level[1] == [(0, 0.0), (30, 0.5), (180, 0.5), (240, 0.0)]    # in 1 s, out last 2 s of 8 s


def test_zoom_and_links(tmp):
    tl, xml, root, srt = load(tmp)
    red = root.find("./sequence/media/video/track/clipitem")
    assert len(param(filt(red, "Basic Motion"), "scale")[1]) == 4
    vlinks = [(l.findtext("mediatype"), l.findtext("trackindex"), l.findtext("clipindex")) for l in red.findall("link")]
    assert vlinks == [("video", "1", "1"), ("audio", "1", "1")]
    first_audio = root.find("./sequence/media/audio/track/clipitem")
    assert first_audio.find("link/linkclipref").text == first_audio.get("id")
    assert {l.findtext("linkclipref") for l in first_audio.findall("link")} >= {red.get("id")}


def test_titles(tmp):
    tl, xml, root, srt = load(tmp)
    gens = list(root.iter("generatoritem"))
    assert [g.findtext("name") for g in gens] == ["Hello", "World"]
    hello = gens[0]
    colour = next(p for p in hello.findall("effect/parameter") if p.findtext("parameterid") == "fontcolor")
    assert [colour.findtext(f"value/{c}") for c in ("red", "green", "blue")] == ["255", "255", "0"]
    assert param(filt(hello, "Opacity"), "opacity")[1] == [(0, 0.0), (15, 100.0), (45, 100.0), (60, 0.0)]


if __name__ == "__main__":
    test_supports_every_feature()
    print("ok test_supports_every_feature")
    tmp = Path(tempfile.mkdtemp())
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and fn.__code__.co_argcount:
            fn(tmp)
            print("ok", name)

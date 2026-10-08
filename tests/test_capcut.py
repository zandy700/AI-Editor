"""CapCut exporter: every feature in FEATURES shows up in the generated draft JSON (CapCut itself isn't run).
Run: .venv/bin/python tests/test_capcut.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from features import full_timeline

from editor.export import export
from editor.export.capcut import SUPPORTS
from editor.timeline import FEATURES

S = 1_000_000


def test_all_features_declared():
    assert SUPPORTS == set(FEATURES)


def draft(tmp):
    return json.loads(export(full_timeline(tmp), "capcut", tmp / "drafts")[0].read_text())


def test_capcut(tmp):
    d = draft(tmp)
    mats = d["materials"]
    by_id = {m["id"]: m for k in ("videos", "audios", "audio_fades", "transitions", "texts", "material_animations")
             for m in mats[k]}
    tracks = {t["type"] + (t.get("name") or ""): t["segments"] for t in d["tracks"]}
    rng = lambda r: (r["start"], r["duration"])
    refs = lambda seg, kind: [by_id[r] for r in seg["extra_material_refs"] if r in by_id and kind in by_id[r].get("type", kind)]

    v0 = tracks["videoV0"]
    # trim + crossfade: red 0-4 and blue 3-7 are cut at the middle of the 1 s overlap (3.5 s)
    assert [(rng(s["target_timerange"]), rng(s["source_timerange"])) for s in v0[:2]] == [
        ((0, 3.5 * S), (2 * S, 3.5 * S)),               # trim: source 2 s in
        ((3.5 * S, 3.5 * S), (5.5 * S, 3.5 * S))]       # blue: source 5 s + half the overlap
    assert v0[-1]["target_timerange"]["start"] + v0[-1]["target_timerange"]["duration"] == 11 * S

    # crossfade: one 叠化 dissolve of the full 1 s, on the first clip only
    (dissolve,) = mats["transitions"]
    assert (dissolve["name"], dissolve["duration"]) == ("叠化", S)
    assert [dissolve["id"] in s["extra_material_refs"] for s in v0] == [True, False, False, False]

    # images: the png becomes a photo material, placed 7-9 s
    assert by_id[v0[2]["material_id"]]["type"] == "photo" and rng(v0[2]["target_timerange"]) == (7 * S, 2 * S)

    # speed 2: 2 s on the timeline eats 4 s of source
    assert v0[3]["speed"] == 2 and rng(v0[3]["target_timerange"]) == (9 * S, 2 * S) \
        and rng(v0[3]["source_timerange"]) == (0, 4 * S)

    # tracks + opacity: overlay on its own, higher track at half opacity, starting at 1 s
    (ov,) = tracks["videoV1"]
    assert ov["clip"]["alpha"] == 0.5 and ov["target_timerange"]["start"] == S
    assert list(tracks).index("videoV1") > list(tracks).index("videoV0")

    # zoom: click at 1 s -> scale 1, 1.5, 1.5, 1 around it
    zoom = next(k for k in v0[0]["common_keyframes"] if "Scale" in k["property_type"])["keyframe_list"]
    assert [(f["time_offset"], f["values"][0]) for f in zoom] == [
        (0.75 * S, 1.0), (1.0 * S, 1.5), (1.6 * S, 1.5), (1.85 * S, 1.0)]

    # fades: picture ramps 0 -> 1 over 0.5 s; the clip's own sound fades in 0.5 s
    alpha = next(k for k in v0[0]["common_keyframes"] if "Alpha" in k["property_type"])["keyframe_list"]
    assert [(f["time_offset"], f["values"][0]) for f in alpha][:2] == [(0, 0), (0.5 * S, 1.0)]
    assert any(f["fade_in_duration"] == 0.5 * S for f in refs(v0[0], "audio_fade"))

    # audio: volume, fade in 1 s / out 2 s
    (music,) = tracks["audioA0"]
    assert music["volume"] == 0.5
    (fade,) = refs(music, "audio_fade")
    assert (fade["fade_in_duration"], fade["fade_out_duration"]) == (S, 2 * S)

    # titles: colour, fade-in/out animations of 0.5 s on the first only
    hello, world = tracks["textTitles"]
    assert json.loads(by_id[hello["material_id"]]["content"])["styles"][0]["fill"]["content"]["solid"]["color"] == [1.0, 1.0, 0.0]
    anims = [(a["type"], a["name"], a["duration"]) for m in refs(hello, "animation") for a in m["animations"]]
    assert anims == [("in", "渐显", 0.5 * S), ("out", "渐隐", 0.5 * S)]
    assert not refs(world, "animation")


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp())
    test_all_features_declared()
    print("ok test_all_features_declared")
    test_capcut(tmp)
    print("ok test_capcut")

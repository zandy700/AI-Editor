"""CapCut draft folder via pyJianYingDraft >= 0.3 (`pip install pyJianYingDraft`). Same engine as the JianYing skill."""
import sys
from pathlib import Path

from ..timeline import FEATURES, probe

# Every feature maps onto something pyJianYingDraft can write. Not yet seen opening in CapCut itself.
SUPPORTS = set(FEATURES)

DEFAULT_ROOT = {
    "darwin": "~/Movies/CapCut/User Data/Projects/com.lveditor.draft",
    "win32": "~/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft",
}


def export(tl, out_dir):
    """`out_dir` is the drafts folder. Pass your CapCut one, or any folder to inspect the result."""
    try:
        import pyJianYingDraft as draft
        from pyJianYingDraft import (ClipSettings, KeyframeProperty as KP, TextIntro, TextOutro, TrackSpec,
                                     TrackType, TransitionType, trange)
    except ImportError:
        raise SystemExit("CapCut export needs: pip install pyJianYingDraft>=0.3")

    us = lambda s: round(s * 1_000_000)
    root = Path(out_dir) if out_dir else Path(DEFAULT_ROOT.get(sys.platform, "capcut_drafts")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    script = draft.DraftFolder(str(root)).create_draft(tl.name, tl.width, tl.height, tl.fps, allow_replace=True)

    made = set()

    def track(kind, name):
        if name not in made:                   # pyJianYingDraft >= 0.3: append_track, not add_track
            script.append_track(TrackSpec(kind, name))
            made.add(name)
        return name

    # Crossfade. The model overlaps clips; a CapCut track can't, so cut both clips at the middle of the overlap and
    # hang a 叠化 (dissolve) transition on the first. The transition spans the same half-before/half-after window,
    # drawing on the media either side of the cut, so the picture matches the overlap.
    adj = {id(c): [c.start, c.dur, c.src] for c in tl.clips}        # start, dur, src after cutting
    dissolve = {}
    for tr in {c.track for c in tl.clips if c.kind == "video"}:
        run = sorted((c for c in tl.clips if c.kind == "video" and c.track == tr), key=lambda c: c.start)
        for prev, c in zip(run, run[1:]):
            if c.crossfade > 0:
                half = c.crossfade / 2
                adj[id(prev)][1] -= half
                adj[id(c)][0] += half
                adj[id(c)][1] -= half
                adj[id(c)][2] += half * c.speed
                dissolve[id(prev)] = c.crossfade
    # ponytail: audio clips don't crossfade (put overlapping music on separate lanes with fade_in/fade_out)

    segs = []                                                         # (segment, track name), added once dressed
    by_id = {}
    for c in sorted(tl.clips, key=lambda c: (c.kind, c.track, c.start)):
        start, dur, src = adj[id(c)]
        rng, source = trange(us(start), us(dur)), trange(us(src), us(dur * c.speed))   # speed: source = dur * speed
        if c.kind == "audio":
            seg = draft.AudioSegment(c.path, rng, source_timerange=source, speed=c.speed, volume=c.volume)
            if c.fade_in or c.fade_out:
                seg.add_fade(us(c.fade_in), us(c.fade_out))
            segs.append((seg, track(TrackType.audio, f"A{c.track}")))
            continue
        seg = draft.VideoSegment(c.path, rng, source_timerange=source, speed=c.speed, volume=c.volume,
                                 clip_settings=ClipSettings(alpha=c.opacity))
        by_id[id(c)] = seg
        shift = start - c.start                                       # zoom times are measured from the clip's start
        for sec, scale in c.zoom:
            seg.add_keyframe(KP.uniform_scale, us(min(max(sec - shift, 0), dur)), scale)
        if c.fade_in or c.fade_out:
            if probe(c.path)["has_audio"]:
                seg.add_fade(us(c.fade_in), us(c.fade_out))           # sound
            for sec, a in [(0, 0), (c.fade_in, c.opacity), (dur - c.fade_out, c.opacity), (dur, 0)]:
                if (sec, a) == (0, 0) and not c.fade_in or (sec, a) == (dur, 0) and not c.fade_out:
                    continue                                          # no fade on that side
                seg.add_keyframe(KP.alpha, us(sec), a)                # picture
        segs.append((seg, track(TrackType.video, f"V{c.track}")))
    for c in tl.clips:
        if id(c) in dissolve:
            by_id[id(c)].add_transition(TransitionType.叠化, duration=us(dissolve[id(c)]))

    for t in tl.titles:
        rgb = tuple(int(t.color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        seg = draft.TextSegment(t.text, trange(us(t.start), us(t.dur)),
                                style=draft.TextStyle(size=t.size / 10, color=rgb),
                                clip_settings=ClipSettings(transform_y=t.y))
        if t.fade:
            seg.add_animation(TextIntro.渐显, us(t.fade)).add_animation(TextOutro.渐隐, us(t.fade))
        segs.append((seg, track(TrackType.text, "Titles")))

    for seg, name in segs:
        script.add_segment(seg, name)
    script.save()
    return [Path(script.save_path)]

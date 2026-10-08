"""MLT XML -> Shotcut (File > Open), Kdenlive, or headless: `melt Name.mlt` / `melt Name.mlt -consumer avformat:out.mp4`.

Layout: track 0 is a black background; every video clip sits on a playlist "lane" composited onto it with qtblend.
Overlapping clips (crossfade) go on a second lane and a `luma` transition dissolves them over the overlap.
Opacity/fades are keyframed `brightness alpha`; sound fades are keyframed `volume gain`; zoom is an `affine` filter.
"""
from math import gcd, log10
from pathlib import Path
from xml.etree import ElementTree as ET

from ..timeline import FEATURES, probe

SUPPORTS = set(FEATURES)


def prop(parent, name, value):
    ET.SubElement(parent, "property", name=name).text = str(value)


def curve(points, level, off=0):
    """MLT animation string from [(frame, value)], or a plain number when nothing moves.
    `off`: a filter on a producer counts frames from the start of the media, not from the clip's in-point."""
    if not points:
        return level
    points = sorted(set(points))
    if points[0][0] > 0:
        points.insert(0, (0, level))
    return ";".join(f"{t + off}={v:g}" for t, v in points)


def export(tl, out_dir):
    fps, f, W, H = tl.fps, tl.frames, tl.width, tl.height
    N = max(f(tl.duration), 1)
    g = gcd(W, H)
    root = ET.Element("mlt", LC_NUMERIC="C", version="7.0.0", title=tl.name)
    ET.SubElement(root, "profile", description=f"{W}x{H} {fps}fps", width=str(W), height=str(H),
                  progressive="1", sample_aspect_num="1", sample_aspect_den="1",
                  display_aspect_num=str(W // g), display_aspect_den=str(H // g),
                  frame_rate_num=str(fps), frame_rate_den="1", colorspace="709")

    n = [0]

    def new_producer(first, last):
        n[0] += 1
        return ET.SubElement(root, "producer", id=f"p{n[0]}", **{"in": str(first), "out": str(last)})

    def fade_filters(p, level, fi, fo, D, service, key):
        """Attach `service` with `key` animated: ramp up over fi frames, down over fo frames.
        Sound is keyframed in dB (`volume level`; `volume gain` can't be animated), picture as `brightness alpha`."""
        db = service == "volume"
        conv = (lambda v: 20 * log10(v) if v > 0 else -90) if db else (lambda v: v)
        pts = []
        if fi:
            pts += [(0, conv(0)), (fi, conv(level))]
        if fo:
            pts += [(D - fo, conv(level)), (D, conv(0))]
        flt = None
        if pts:
            flt = ET.SubElement(p, "filter", mlt_service=service)
            prop(flt, "level" if db else key, curve(pts, conv(level), int(p.get("in"))))
        elif level != 1:
            flt = ET.SubElement(p, "filter", mlt_service=service)
            prop(flt, key, level)

    def clip_producer(c, D, fade_in, fade_out):
        """fade_in/out here are the SOUND fades in frames (clip fades plus crossfade overlaps)."""
        info = probe(c.path)
        if info["is_image"]:
            p = new_producer(0, D - 1)
            prop(p, "mlt_service", "qimage")
            prop(p, "resource", c.path)
            prop(p, "length", D)
        elif c.speed != 1:
            first = round(c.src / c.speed * fps)       # timewarp positions are in output time
            p = new_producer(first, first + D - 1)
            prop(p, "mlt_service", "timewarp")
            prop(p, "resource", f"{c.speed:g}:{c.path}")
        else:
            p = new_producer(f(c.src), f(c.src) + D - 1)
            prop(p, "resource", c.path)
        if c.kind == "audio":
            prop(p, "video_index", -1)
        if c.zoom:                                      # scale about the frame centre
            a = ET.SubElement(p, "filter", mlt_service="affine")
            zoom = sorted((f(sec), s) for sec, s in c.zoom)
            # melt misbehaves past the last animated rect, so pin the clip's first and last frame too
            zoom = [(0, zoom[0][1])] * (zoom[0][0] > 0) + zoom + [(D - 1, zoom[-1][1])] * (zoom[-1][0] < D - 1)
            keys = []
            for t, s in zoom:
                w, h = W * s, H * s
                keys.append(f"{t + int(p.get('in'))}={(W - w) / 2:g} {(H - h) / 2:g} {w:g} {h:g} 1")
            prop(a, "transition.rect", ";".join(keys))
            prop(a, "transition.distort", 0)
        if c.kind == "video":
            fade_filters(p, c.opacity, f(c.fade_in), f(c.fade_out), D, "brightness", "alpha")
        if info["has_audio"] or c.kind == "audio":
            fade_filters(p, c.volume, fade_in, fade_out, D, "volume", "gain")
        return p.get("id")

    def playlist(pid, items):
        """items: [(start_frame, D, producer_id)] sorted and non-overlapping; blanks fill the gaps."""
        pl = ET.SubElement(root, "playlist", id=pid)
        cursor = 0
        for start, D, prod in items:
            if start > cursor:
                ET.SubElement(pl, "blank", length=str(start - cursor))
            first = int(root.find(f"producer[@id='{prod}']").get("in"))
            ET.SubElement(pl, "entry", producer=prod, **{"in": str(first), "out": str(first + D - 1)})
            cursor = start + D
        return pid

    by_start = lambda cs: sorted(cs, key=lambda c: c.start)
    video = by_start(c for c in tl.clips if c.kind == "video")
    audio = by_start(c for c in tl.clips if c.kind == "audio")

    # background: solid black for the whole timeline, so transparency composites to black
    bg = new_producer(0, N - 1)
    prop(bg, "mlt_service", "color")
    prop(bg, "resource", "black")
    tracks = [(playlist("background", [(0, N, bg.get("id"))]), "bg")]
    trans = []   # transitions, in the order they must be applied (bottom to top)

    # --- video tracks -> lanes
    for tr in sorted({c.track for c in video}):
        mine = [c for c in video if c.track == tr]
        lanes, placed = [], {}                               # lanes: [[(start_f, D, producer, clip)]]
        # which clips dissolve into the one before them (overlap + crossfade set)
        prev_of = {id(b): a for a, b in zip(mine, mine[1:]) if b.crossfade > 0}
        next_of = {id(a): b for a, b in zip(mine, mine[1:]) if b.crossfade > 0}
        for c in mine:
            fs = f(c.start)
            D = max(f(c.start + c.dur) - fs, 1)
            lane = next((i for i, l in enumerate(lanes) if l[-1][0] + l[-1][1] <= fs), None)
            if lane is None:
                lanes.append([])
                lane = len(lanes) - 1
            x_in = f(c.crossfade) if id(c) in prev_of else 0
            x_out = f(next_of[id(c)].crossfade) if id(c) in next_of else 0
            prod = clip_producer(c, D, max(f(c.fade_in), x_in), max(f(c.fade_out), x_out))
            lanes[lane].append((fs, D, prod, c))
            placed[id(c)] = (lane, fs, D, x_in, x_out)
        base = len(tracks)
        for i, l in enumerate(lanes):
            tracks.append((playlist(f"v{tr}_{i}", [(s, d, p) for s, d, p, _ in l]), "video"))
        # dissolves first, so each lane holds the blended picture before it is composited
        for c in mine:
            if id(c) in prev_of:
                a = prev_of[id(c)]
                la, lb = placed[id(a)][0], placed[id(c)][0]
                if la != lb:
                    t0 = placed[id(c)][1]
                    trans.append(dict(mlt_service="luma", a_track=base + min(la, lb), b_track=base + max(la, lb),
                                      **{"in": t0, "out": t0 + placed[id(c)][3] - 1},
                                      props=[("reverse", int(lb < la)), ("softness", 0)]))
        for i, l in enumerate(lanes):
            for s, d, _, c in l:
                lane, fs, D, x_in, x_out = placed[id(c)]
                lo, hi = fs, fs + D - 1
                if i > 0 and (id(c) in prev_of and placed[id(prev_of[id(c)])][0] != i):
                    lo += x_in                           # the lower lane already carries this overlap
                if i > 0 and (id(c) in next_of and placed[id(next_of[id(c)])][0] != i):
                    hi -= x_out
                if i == 0:                               # one transition for the whole lane is enough
                    continue
                if lo <= hi:
                    trans.append(dict(mlt_service="qtblend", a_track=0, b_track=base + i, **{"in": lo, "out": hi}))
            if i == 0:
                trans.append(dict(mlt_service="qtblend", a_track=0, b_track=base))

    # --- titles: overlapping ones need separate lanes
    title_lanes = []
    for ti in sorted(tl.titles, key=lambda x: x.start):
        lane = next((l for l in title_lanes if l[-1].start + l[-1].dur <= ti.start), None)
        title_lanes.append([ti]) if lane is None else lane.append(ti)
    for i, lane in enumerate(title_lanes):
        items = []
        for ti in lane:
            D = max(f(ti.start + ti.dur) - f(ti.start), 1)
            p = new_producer(0, D - 1)
            prop(p, "mlt_service", "color")
            prop(p, "resource", "#00000000")
            d = ET.SubElement(p, "filter", mlt_service="dynamictext")
            h = 10                                       # text box is 10% of frame height, centred on y
            top = max(0, min(100 - h, (1 - ti.y) / 2 * 100 - h / 2))
            for k, v in [("argument", ti.text), ("geometry", f"0%/{top:g}%:100%x{h}%:100"),
                         ("family", "Sans"), ("size", ti.size), ("weight", 700),
                         ("fgcolour", "0x" + ti.color.lstrip("#").ljust(6, "0")[:6] + "ff"), ("bgcolour", "0x00000000"),
                         ("olcolour", "0x000000ff"), ("outline", 3),
                         ("halign", "center"), ("valign", "middle")]:
                prop(d, k, v)
            fade_filters(p, 1, f(ti.fade), f(ti.fade), D, "brightness", "alpha")
            items.append((f(ti.start), D, p.get("id")))
        tracks.append((playlist(f"t{i}", items), "video"))
        trans.append(dict(mlt_service="qtblend", a_track=0, b_track=len(tracks) - 1))

    # --- standalone audio lanes (overlaps within one lane are not expected)
    for tr in sorted({c.track for c in audio}):
        items = []
        for c in (c for c in audio if c.track == tr):
            fs = f(c.start)
            D = max(f(c.start + c.dur) - fs, 1)
            items.append((fs, D, clip_producer(c, D, f(c.fade_in), f(c.fade_out))))
        tracks.append((playlist(f"a{tr}", items), "audio"))

    tractor = ET.SubElement(root, "tractor", id="main", **{"in": "0", "out": str(N - 1)})
    mt = ET.SubElement(tractor, "multitrack")
    for pid, _ in tracks:
        ET.SubElement(mt, "track", producer=pid)
    for i in range(1, len(tracks)):                      # sound of every track, summed
        ET.SubElement(tractor, "transition", mlt_service="mix", a_track="0", b_track=str(i), sum="1", always_active="1")
    for t in trans:
        extra = t.pop("props", [])
        el = ET.SubElement(tractor, "transition", **{k: str(v) for k, v in t.items()})
        for k, v in extra:
            prop(el, k, v)
    root.set("producer", "main")

    ET.indent(root)
    path = Path(out_dir) / f"{tl.name}.mlt"
    path.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode"))
    return [path]

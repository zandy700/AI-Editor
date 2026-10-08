"""FCPXML 1.9 -> Final Cut Pro (File > Import > XML) and DaVinci Resolve (File > Import > Timeline).

Every feature in editor.timeline.FEATURES is mapped natively. Unverified (no Final Cut here): the timeMap `start`
semantics (written in the retimed local timeline), the Basic Title uid/Position key, and that FCP accepts the dissolve
without an explicit audio crossfade filter (the sound of the two clips simply cuts at the dissolve's centre).
Limits: crossfade works on the main video track (track 0) only; elsewhere clips just overlap. A clip that takes part
in a crossfade drops the fade on the side the dissolve replaces."""
import math
from pathlib import Path
from xml.etree import ElementTree as ET

from ..timeline import FEATURES, probe

SUPPORTS = set(FEATURES)
GAP_START = 3600   # Final Cut gives gaps (and stills) a 1h start; clips connected to a gap offset from it
TITLE_UID = "/Library/Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"
DISSOLVE_UID = "FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265"


def _fade_pts(start, end, fi, fo, peak):
    """Keyframes (frame, value) for a fade in at `start` and a fade out ending at `end`."""
    pts = []
    if fi:
        pts += [(start, 0), (start + fi, peak)]
    if fo:
        pts += [(end - fo, peak), (end, 0)]
    return sorted(dict(pts).items())


def export(tl, out_dir):
    fps = tl.fps
    F = lambda s: round(s * fps)               # seconds -> frames
    t = lambda f: f"{f}/{fps}s"                # frames -> FCPXML time
    g = GAP_START * fps
    root = ET.Element("fcpxml", version="1.9")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", name=f"FFVideoFormat{tl.height}p{fps}",
                  frameDuration=f"1/{fps}s", width=str(tl.width), height=str(tl.height))
    assets = {}
    for c in tl.clips:
        if c.path in assets:
            continue
        info = probe(c.path)
        attrs = dict(id=f"a{len(assets) + 1}", name=Path(c.path).stem, start="0s", src=Path(c.path).as_uri())
        if info["is_image"]:       # stills: zero-length asset on its own format, placed with <video>
            ET.SubElement(res, "format", id=f"f{len(assets) + 1}", name="FFVideoFormatRateUndefined",
                          width=str(info["width"]), height=str(info["height"]))
            attrs.update(duration="0s", hasVideo="1", format=f"f{len(assets) + 1}")
        else:
            attrs.update(duration=t(F(info["dur"])))
            if info["has_video"]:
                attrs.update(hasVideo="1", format="r1")
            if info["has_audio"]:
                attrs.update(hasAudio="1", audioSources="1", audioChannels="2", audioRate="48000")
        assets[c.path] = attrs["id"]
        ET.SubElement(res, "asset", **attrs)
    if tl.titles:
        ET.SubElement(res, "effect", id="rT", name="Basic Title", uid=TITLE_UID)

    seq = ET.SubElement(
        ET.SubElement(ET.SubElement(ET.SubElement(root, "library"), "event", name=tl.name),
                      "project", name=tl.name),
        "sequence", format="r1", duration=t(F(tl.duration)), tcStart="0s", tcFormat="NDF",
        audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")

    def item(c):
        """Frames: `off` on the timeline, `start` in the clip's own (retimed) time, `dur` on the timeline."""
        still = probe(c.path)["is_image"]
        return dict(c=c, off=F(c.start), dur=max(1, F(c.dur)), start=g if still else F(c.src / c.speed),
                    fi=F(c.fade_in), fo=F(c.fade_out))

    def clip_el(parent, it, xml_offset, lane):
        c, info = it["c"], probe(it["c"].path)
        still = info["is_image"]
        attrs = dict(ref=assets[c.path], name=Path(c.path).stem, offset=t(xml_offset),
                     start=t(it["start"]), duration=t(it["dur"]))
        if lane:
            attrs["lane"] = str(lane)
        el = ET.SubElement(parent, "video" if still else "asset-clip", **attrs)
        local = lambda tf: it["start"] + tf - it["off"]          # timeline frame -> clip-local frame
        if c.speed != 1 and not still:
            tm = ET.SubElement(el, "timeMap")                    # output time -> source time, linear
            ad = F(info["dur"])
            ET.SubElement(tm, "timept", time="0s", value="0s", interp="linear")
            ET.SubElement(tm, "timept", time=t(round(ad / c.speed)), value=t(ad), interp="linear")
        if c.zoom and c.kind == "video":
            anim = ET.SubElement(ET.SubElement(ET.SubElement(el, "adjust-transform"), "param", name="scale"),
                                 "keyframeAnimation")
            for sec, scale in c.zoom:
                ET.SubElement(anim, "keyframe", time=t(local(F(c.start + sec))), value=f"{scale:g} {scale:g}")
        end = it["off"] + it["dur"]
        pts = _fade_pts(it["off"], end, it["fi"], it["fo"], c.opacity)
        if c.kind == "video" and (c.opacity != 1 or pts):
            blend = ET.SubElement(el, "adjust-blend", amount=f"{c.opacity:g}")
            if pts:
                anim = ET.SubElement(ET.SubElement(blend, "param", name="amount"), "keyframeAnimation")
                for f, v in pts:
                    ET.SubElement(anim, "keyframe", time=t(local(f)), value=f"{v:g}")
        if (c.kind == "audio" or info["has_audio"]) and (c.volume != 1 or it["fi"] or it["fo"]):
            vol = ET.SubElement(el, "adjust-volume",
                                amount=f"{20 * math.log10(c.volume) if c.volume > 0 else -96:.1f}dB")
            if it["fi"] or it["fo"]:
                p = ET.SubElement(vol, "param", name="amount")
                if it["fi"]:
                    ET.SubElement(p, "fadeIn", type="easeIn", duration=t(it["fi"]))
                if it["fo"]:
                    ET.SubElement(p, "fadeOut", type="easeOut", duration=t(it["fo"]))
        return el

    # Main video track = the spine. A crossfade (clips overlap by x) becomes a centred FCP transition:
    # the previous clip is cut at P, the next starts at P, and FCP fills the dissolve from both clips' handles.
    seq_items, prev = [], None
    for c in sorted((c for c in tl.clips if c.kind == "video" and c.track == 0), key=lambda c: c.start):
        it = item(c)
        xf = F(c.crossfade)
        if prev and xf >= 2 and abs(it["off"] - (prev["off"] + prev["dur"] - xf)) <= 1:
            p = it["off"] + xf // 2
            prev["dur"] = p - prev["off"]
            it["start"] += p - it["off"]
            it["dur"] -= p - it["off"]
            seq_items.append(("transition", it["off"], xf))
            it["off"], it["fi"], prev["fo"] = p, 0, 0
        seq_items.append(("clip", it))
        prev = it

    slots, cursor = [], 0      # (element, timeline start, timeline end, clip-local time at its start)
    gap = lambda a, b: (ET.SubElement(spine, "gap", name="Gap", offset=t(a), start=t(g), duration=t(b - a)), a, b, g)
    for entry in seq_items:
        if entry[0] == "transition":
            tr = ET.SubElement(spine, "transition", name="Cross Dissolve", offset=t(entry[1]), duration=t(entry[2]))
            if res.find("effect[@id='rX']") is None:
                ET.SubElement(res, "effect", id="rX", name="Cross Dissolve", uid=DISSOLVE_UID)
            ET.SubElement(tr, "filter-video", ref="rX", name="Cross Dissolve")
            continue
        it = entry[1]
        if it["off"] > cursor:
            slots.append(gap(cursor, it["off"]))
        slots.append((clip_el(spine, it, it["off"], 0), it["off"], it["off"] + it["dur"], it["start"]))
        cursor = it["off"] + it["dur"]
    if cursor < F(tl.duration) or not slots:
        slots.append(gap(cursor, max(F(tl.duration), 1)))

    def attach(frame):
        el, s0, _, base = next((s for s in slots if s[1] <= frame < s[2]), slots[-1])
        return el, base + (frame - s0)

    for c in tl.clips:
        if c.kind == "video" and c.track == 0:
            continue
        it = item(c)
        el, offset = attach(it["off"])
        clip_el(el, it, offset, c.track if c.kind == "video" else -(c.track + 1))
    lane = max((c.track for c in tl.clips if c.kind == "video"), default=0) + 1
    for i, ti in enumerate(sorted(tl.titles, key=lambda x: x.start), 1):
        a, d = F(ti.start), max(1, F(ti.dur))
        el, offset = attach(a)
        node = ET.SubElement(el, "title", ref="rT", lane=str(lane), name=ti.text[:40],
                             offset=t(offset), start=t(g), duration=t(d))
        if ti.fade:
            blend = ET.SubElement(node, "adjust-blend", amount="1")
            anim = ET.SubElement(ET.SubElement(blend, "param", name="amount"), "keyframeAnimation")
            for f, v in _fade_pts(0, d, F(ti.fade), F(ti.fade), 1):
                ET.SubElement(anim, "keyframe", time=t(g + f), value=f"{v:g}")
        ET.SubElement(node, "param", name="Position", key="9999/999166631/999166633/1/100/101",
                      value=f"0 {ti.y * tl.height / 2:.0f}")
        ET.SubElement(ET.SubElement(node, "text"), "text-style", ref=f"ts{i}").text = ti.text
        rgb = " ".join(f"{int(ti.color[k:k + 2], 16) / 255:g}" for k in (1, 3, 5))
        ET.SubElement(ET.SubElement(node, "text-style-def", id=f"ts{i}"), "text-style",
                      font="Helvetica", fontSize=str(ti.size), fontColor=f"{rgb} 1", alignment="center")

    ET.indent(root)
    path = Path(out_dir) / f"{tl.name}.fcpxml"
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
                    + ET.tostring(root, encoding="unicode"))
    return [path]

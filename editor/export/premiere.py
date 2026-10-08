"""FCP7 XML (xmeml v4) -> Premiere Pro (File > Import). Titles also go out as an .srt to import as captions.

Mapping: speed = Time Remap filter, opacity/fades = Opacity and Audio Levels filters (keyframed for fades),
crossfade = <transitionitem> straddling a cut, stills = <stillframe>, titles = Text generatoritems.
Nothing here has been opened in Premiere; see the "unverified" notes in the README.
"""
from pathlib import Path
from xml.etree import ElementTree as ET

from ..timeline import FEATURES, probe

SUPPORTS = set(FEATURES)
# Unverified guesses (no Premiere here): keyframe <when> is clip-local timeline frames; Time Remap on the audio
# clipitem; Text generator params (origin sign, font colour layout) and whether Premiere keeps a Text generator
# or turns it offline - the .srt sidecar is the fallback that carries text + timing (not fade/colour).


def mk(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        e.text = str(text)
    return e


def num(v):
    return f"{v:.6g}"


def plan(seq, has, f):
    """Entries for the clips of `seq` that carry this media, with crossfades resolved.

    The model overlaps B onto A by `crossfade`. FCP7 wants B to start where A ends and a transition to straddle
    that cut, so the cut goes in the middle of the overlap: A loses its tail past the cut, B its head before it.
    The transition then spans exactly the overlap and shows the same picture as the overlap would.
    """
    joins = {}                                   # seq index of B -> (overlap start, overlap end) in frames
    for i in range(1, len(seq)):
        a, b = seq[i - 1], seq[i]
        if b.crossfade > 0 and has(a) and has(b) and f(a.start + a.dur) > f(b.start):
            joins[i] = (f(b.start), f(a.start + a.dur))
    out = []
    for i, c in enumerate(seq):
        if not has(c):
            continue
        s, e = f(c.start), f(c.start + c.dur)
        s2 = sum(joins[i]) // 2 if i in joins else s
        e2 = sum(joins[i + 1]) // 2 if i + 1 in joins else e
        out.append(dict(c=c, s=s, e=e, s2=s2, e2=e2, head=s2 - s, join_in=joins.get(i), join_out=joins.get(i + 1)))
    return out


def envelope(ent, base, f):
    """Fade keyframes [(clip-local frame, value)] scaled by `base`, or [] when the clip doesn't fade."""
    c = ent["c"]
    fi = 0 if ent["join_in"] else f(c.fade_in)    # a crossfade already fades that edge
    fo = 0 if ent["join_out"] else f(c.fade_out)
    if not (fi or fo):
        return []
    n = ent["e"] - ent["s"]
    pts = [(0, 0 if fi else 1)] + ([(fi, 1)] if fi else []) + ([(n - fo, 1)] if fo else []) + [(n, 0 if fo else 1)]
    last = ent["e2"] - ent["s2"]
    kf = {}
    for t, v in pts:                             # shift into the (possibly head-trimmed) clip and clamp
        kf[min(max(t - ent["head"], 0), last)] = v * base
    return sorted(kf.items())


def export(tl, out_dir):
    fps, f = tl.fps, tl.frames
    count = [0]

    def new_id(prefix="clipitem"):
        count[0] += 1
        return f"{prefix}-{count[0]}"

    def add_rate(p):
        r = mk(p, "rate")
        mk(r, "timebase", fps)
        mk(r, "ntsc", "FALSE")

    info = lambda c: probe(c.path)
    by_start = lambda cs: sorted(cs, key=lambda c: c.start)
    videos = [c for c in tl.clips if c.kind == "video"]
    audios = [c for c in tl.clips if c.kind == "audio"]
    vtracks = sorted({c.track for c in videos})

    # ---- plan every track first so clipitems can <link> to their picture/sound partner ----
    vplans = []        # (video track entries), one per video track
    aplans = []        # entries per audio track: the sound inside each video track, then standalone lanes
    for tr in vtracks:
        seq = by_start(c for c in videos if c.track == tr)
        vplans.append(plan(seq, lambda c: True, f))
        aplans.append(plan(seq, lambda c: info(c)["has_audio"], f))
    for tr in sorted({c.track for c in audios}):
        aplans.append(plan(by_start(c for c in audios if c.track == tr), lambda c: True, f))
    for plans, kind in ((vplans, "video"), (aplans, "audio")):
        for ti, ents in enumerate(plans, 1):
            for ci, ent in enumerate(ents, 1):
                ent.update(id=new_id(), kind=kind, trackindex=ti, clipindex=ci)
    pic = {id(ent["c"]): ent for ents in vplans for ent in ents}                 # clip -> its picture entry
    snd = {id(ent["c"]): ent for ents in aplans[:len(vtracks)] for ent in ents}  # clip -> its embedded-sound entry

    # ---- document ----
    root = ET.Element("xmeml", version="4")
    seq = mk(root, "sequence", id="seq1")
    mk(seq, "name", tl.name)
    mk(seq, "duration", f(tl.duration))
    add_rate(seq)
    media = mk(seq, "media")
    vid, aud = mk(media, "video"), mk(media, "audio")
    sc = mk(mk(vid, "format"), "samplecharacteristics")
    mk(sc, "width", tl.width)
    mk(sc, "height", tl.height)
    mk(sc, "pixelaspectratio", "square")
    mk(aud, "numOutputChannels", 2)

    def param(eff, pid, name, value=None, lo=None, hi=None, kfs=()):
        p = mk(eff, "parameter", authoringApp="PremierePro")
        mk(p, "parameterid", pid)
        mk(p, "name", name)
        if lo is not None:
            mk(p, "valuemin", num(lo))
            mk(p, "valuemax", num(hi))
        if isinstance(value, dict):
            v = mk(p, "value")
            for k, x in value.items():
                mk(v, k, x)
        elif value is not None:
            mk(p, "value", value if isinstance(value, str) else num(value))
        for when, val in kfs:
            k = mk(p, "keyframe")
            mk(k, "when", when)
            mk(k, "value", num(val))
        return p

    def effect(parent, name, eid, cat, mediatype, etype="motion"):
        eff = mk(mk(parent, "filter"), "effect")
        for tag, text in [("name", name), ("effectid", eid), ("effectcategory", cat),
                          ("effecttype", etype), ("mediatype", mediatype)]:
            mk(eff, tag, text)
        return eff

    def opacity(parent, value, kfs):
        param(effect(parent, "Opacity", "opacity", "motion", "video"), "opacity", "opacity", value * 100, 0, 100,
              [(w, v * 100) for w, v in kfs])

    files = {}

    def clipitem(track, ent):
        c, kind = ent["c"], ent["kind"]
        inf = info(c)
        image = inf["is_image"]
        speed = 1.0 if image else c.speed
        s, e = ent["s2"], ent["e2"]
        in_ = 0 if image else f(c.src) + round(ent["head"] * speed)      # source frames consumed = timeline * speed
        out = in_ + (e - s if image else round((e - s) * speed))
        file_dur = f(3600) if image else f(inf["dur"])                   # stills have no length: say an hour

        if ent["join_in"]:                                               # transition straddles the cut at s
            ti = mk(track, "transitionitem")
            mk(ti, "start", ent["join_in"][0])
            mk(ti, "end", ent["join_in"][1])
            mk(ti, "alignment", "center")
            add_rate(ti)
            eff = mk(ti, "effect")
            if kind == "video":
                for tag, text in [("name", "Cross Dissolve"), ("effectid", "Cross Dissolve"),
                                  ("effectcategory", "Dissolve"), ("effecttype", "transition"),
                                  ("mediatype", "video"), ("wipecode", 0), ("wipeaccuracy", 100),
                                  ("startratio", 0), ("endratio", 1), ("reverse", "FALSE")]:
                    mk(eff, tag, text)
            else:
                for tag, text in [("name", "Cross Fade (+3dB)"), ("effectid", "Cross Fade (+3dB)"),
                                  ("effectcategory", "Cross Fade"), ("effecttype", "transition"),
                                  ("mediatype", "audio")]:
                    mk(eff, tag, text)

        ci = mk(track, "clipitem", id=ent["id"])
        mk(ci, "name", Path(c.path).stem)
        mk(ci, "enabled", "TRUE")
        mk(ci, "duration", file_dur)
        add_rate(ci)
        mk(ci, "start", s)
        mk(ci, "end", e)
        mk(ci, "in", in_)
        mk(ci, "out", out)
        if image:
            mk(ci, "stillframe", "TRUE")
        if c.path in files:                                              # later uses reference the first definition
            mk(ci, "file", id=files[c.path])
        else:
            files[c.path] = fid = f"file-{len(files) + 1}"
            fe = mk(ci, "file", id=fid)
            mk(fe, "name", Path(c.path).name)
            mk(fe, "pathurl", Path(c.path).as_uri().replace("file:///", "file://localhost/"))
            add_rate(fe)
            mk(fe, "duration", file_dur)
            fm = mk(fe, "media")
            if inf["has_video"]:
                sc = mk(mk(fm, "video"), "samplecharacteristics")
                mk(sc, "width", inf["width"])
                mk(sc, "height", inf["height"])
            if inf["has_audio"]:
                sc = mk(mk(fm, "audio"), "samplecharacteristics")
                mk(sc, "depth", 16)
                mk(sc, "samplerate", 48000)
        if kind == "audio":
            st = mk(ci, "sourcetrack")
            mk(st, "mediatype", "audio")
            mk(st, "trackindex", 1)

        if kind == "video":
            if c.zoom:
                kfs = [(min(max(f(sec) - ent["head"], 0), e - s), scale * 100) for sec, scale in c.zoom]
                param(effect(ci, "Basic Motion", "basic", "motion", "video"), "scale", "Scale",
                      c.zoom[0][1] * 100, 0, 1000, kfs)
            fade = envelope(ent, c.opacity, f)
            if c.opacity != 1 or fade:
                opacity(ci, c.opacity, fade)
        else:
            fade = envelope(ent, c.volume, f)
            if c.volume != 1 or fade:
                param(effect(ci, "Audio Levels", "audiolevels", "audiolevels", "audio", "audiolevels"),
                      "level", "Level", c.volume, 0, 3.98109, fade)
        if speed != 1:
            eff = effect(ci, "Time Remap", "timeremap", "motion", kind)
            param(eff, "variablespeed", "variablespeed", 0, 0, 1)
            param(eff, "speed", "speed", speed * 100, -100000, 100000)       # percent
            param(eff, "reverse", "reverse", "FALSE")
            param(eff, "frameblending", "frameblending", "FALSE")

        links = [ent]
        if kind == "video" and id(c) in snd:
            links.append(snd[id(c)])
        elif kind == "audio" and snd.get(id(c)) is ent:
            links.append(pic[id(c)])
        for l in links:
            lk = mk(ci, "link")
            mk(lk, "linkclipref", l["id"])
            mk(lk, "mediatype", l["kind"])
            mk(lk, "trackindex", l["trackindex"])
            mk(lk, "clipindex", l["clipindex"])

    for ents in vplans:
        track = mk(vid, "track")
        for ent in ents:
            clipitem(track, ent)

    # ---- titles: Text generators on tracks above the picture; overlapping titles get their own track ----
    lanes = []
    for ti in sorted(tl.titles, key=lambda x: x.start):
        lane = next((l for l in lanes if l[-1].start + l[-1].dur <= ti.start), None)
        lanes.append([ti]) if lane is None else lane.append(ti)
    for lane in lanes:
        track = mk(vid, "track")
        for ti in lane:
            s, e = f(ti.start), f(ti.start + ti.dur)
            g = mk(track, "generatoritem", id=new_id("generatoritem"))
            for tag, text in [("name", ti.text[:40]), ("enabled", "TRUE"), ("duration", e - s)]:
                mk(g, tag, text)
            add_rate(g)
            for tag, text in [("start", s), ("end", e), ("in", 0), ("out", e - s),
                              ("anamorphic", "FALSE"), ("alphatype", "black")]:
                mk(g, tag, text)
            eff = mk(g, "effect")
            for tag, text in [("name", "Text"), ("effectid", "Text"), ("effectcategory", "Text"),
                              ("effecttype", "generator"), ("mediatype", "video")]:
                mk(eff, tag, text)
            r, gr, b = (int(ti.color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            param(eff, "str", "Text", ti.text)
            param(eff, "fontname", "Font", "Helvetica")
            param(eff, "fontsize", "Size", ti.size, 0, 200)
            param(eff, "fontalign", "Alignment", "Center")
            param(eff, "fontcolor", "Font Color", dict(alpha=255, red=r, green=gr, blue=b))
            param(eff, "origin", "Origin", dict(horiz=0, vert=num(ti.y / 2)))   # -0.5 bottom .. 0.5 top
            if ti.fade:
                n, fd = e - s, f(ti.fade)
                opacity(g, 1, [(0, 0), (fd, 1), (n - fd, 1), (n, 0)])

    for ents in aplans:
        track = mk(aud, "track")
        for ent in ents:
            clipitem(track, ent)

    ET.indent(root)
    out = Path(out_dir)
    xml = out / f"{tl.name}.premiere.xml"
    xml.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
                   + ET.tostring(root, encoding="unicode"))
    written = [xml]
    if tl.titles:
        srt = out / f"{tl.name}.srt"
        srt.write_text(tl.srt())
        written.append(srt)
    return written

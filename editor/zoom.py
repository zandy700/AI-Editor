"""Click-driven zoom, as in the JianYing skill's recorder: a zoom in and out around each click."""
import json


def apply_click_zoom(clip, events, scale=1.5, ramp=0.25, hold=0.6):
    """`events`: click times in seconds from the clip's start (list, or path to a JSON list)."""
    if isinstance(events, str):
        events = json.load(open(events))
    keys = []
    for t in sorted(events):
        keys += [(max(t - ramp, 0), 1.0), (t, scale), (t + hold, scale), (t + hold + ramp, 1.0)]
    clip.zoom = [(max(0, min(t, clip.dur)), s) for t, s in keys]
    return clip

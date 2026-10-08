"""Editor-neutral timeline. Every exporter reads this and nothing else."""
import json
import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path


FEATURES = ("trim", "tracks", "volume", "titles", "zoom", "speed", "opacity", "fades", "crossfade", "images")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass
class Clip:
    path: str
    start: float                 # position on the timeline (s)
    dur: float                   # length on the timeline (s)
    src: float = 0.0             # in-point inside the source file (s)
    kind: str = "video"          # "video" | "audio"
    track: int = 0               # video: 0 = main track, 1+ = overlays. audio: lane number
    volume: float = 1.0
    speed: float = 1.0           # 2.0 = twice as fast; `dur` stays the length on the timeline, so 2x consumes 2*dur of source
    opacity: float = 1.0         # picture only
    fade_in: float = 0.0         # seconds; fades picture from black/transparent AND sound from silence
    fade_out: float = 0.0
    crossfade: float = 0.0       # dissolve from the previous clip on this track: this clip OVERLAPS it by this many
                                 # seconds (start = previous end - crossfade); both dissolve across the overlap
    zoom: list = field(default_factory=list)   # [(seconds into clip, scale)], 1.0 = no zoom

    def __post_init__(self):
        self.zoom = [tuple(z) for z in self.zoom]   # JSON hands back lists


@dataclass
class Title:
    text: str
    start: float
    dur: float
    y: float = -0.8              # -1 bottom .. 1 top
    size: int = 60
    fade: float = 0.0            # seconds of fade in and fade out
    color: str = "#ffffff"


@dataclass
class Timeline:
    name: str = "Edit"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    clips: list = field(default_factory=list)
    titles: list = field(default_factory=list)

    def _end(self, kind, track):
        return max((c.start + c.dur for c in self.clips if c.kind == kind and c.track == track), default=0.0)

    def add_clip(self, path, dur=None, src=0.0, start=None, track=0, kind="video", **kw):
        """Add a piece of `path`. `start` defaults to the end of that track (minus `crossfade`), so calls chain.
        Stills (png/jpg/...) have no length of their own: pass `dur`."""
        path = str(Path(path).resolve())
        info = probe(path)
        if dur is None:
            if info["is_image"]:
                raise ValueError(f"{path} is a still image: pass dur=")
            dur = (info["dur"] - src) / kw.get("speed", 1.0)
        start = self._end(kind, track) - kw.get("crossfade", 0.0) if start is None else start
        clip = Clip(path, start, dur, src, kind, track, **kw)
        self.clips.append(clip)
        return clip

    def add_audio(self, path, dur=None, src=0.0, start=None, track=0, **kw):
        return self.add_clip(path, dur, src, start, track, kind="audio", **kw)

    def add_title(self, text, start, dur, **kw):
        title = Title(text, start, dur, **kw)
        self.titles.append(title)
        return title

    @property
    def duration(self):
        ends = [c.start + c.dur for c in self.clips] + [t.start + t.dur for t in self.titles]
        return max(ends, default=0.0)

    def frames(self, seconds):
        return round(seconds * self.fps)

    def srt(self):
        """Titles as SRT text (Premiere and others import this as captions)."""
        def ts(s):
            ms = round(s * 1000)
            return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
        return "".join(
            f"{i}\n{ts(t.start)} --> {ts(t.start + t.dur)}\n{t.text}\n\n"
            for i, t in enumerate(sorted(self.titles, key=lambda t: t.start), 1))

    def save(self, path):
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text())
        d["clips"] = [Clip(**c) for c in d.get("clips", [])]
        d["titles"] = [Title(**t) for t in d.get("titles", [])]
        return cls(**d)


@lru_cache(maxsize=None)
def probe(path):
    """Duration, size, and stream info for a media file, via ffprobe."""
    is_image = Path(path).suffix.lower() in IMAGE_EXT
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    duration = info["format"].get("duration", "")
    return {
        "dur": 0.0 if is_image or not duration.replace(".", "").isdigit() else float(duration),
        "is_image": is_image,
        "has_video": v is not None,
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "width": v["width"] if v else 0,
        "height": v["height"] if v else 0,
    }

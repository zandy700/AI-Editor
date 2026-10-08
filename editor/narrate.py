"""Script -> voiceover + subtitles timed to the speech (`pip install edge-tts`)."""
import asyncio
import re
import tempfile
from pathlib import Path

from .timeline import probe


def split_sentences(text):
    parts = re.split(r"(?<=[.!?。！？，,;；\n])\s*", text)
    return [p.strip() for p in parts if p.strip(" ，,;；.\n")]


def narrate(tl, text, voice="en-US-AriaNeural", start=None, gap=0.1, out_dir=None, zh_voice="zh-CN-XiaoxiaoNeural"):
    """Speak each sentence, put its audio on the timeline, and show it as a title for exactly as long as it plays.
    Sentences containing Chinese use `zh_voice` (an English voice returns no audio for them)."""
    try:
        import edge_tts
    except ImportError:
        raise SystemExit("narrate needs: pip install edge-tts")
    out_dir = Path(out_dir or tempfile.mkdtemp(prefix="narration_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cursor = tl._end("audio", 0) if start is None else start
    for i, sentence in enumerate(split_sentences(text)):
        mp3 = out_dir / f"{i:03}.mp3"
        v = zh_voice if re.search(r"[\u4e00-\u9fff]", sentence) else voice
        asyncio.run(edge_tts.Communicate(sentence.rstrip(".,;，；"), v).save(str(mp3)))
        dur = probe(str(mp3))["dur"]
        tl.add_audio(mp3, dur=dur, start=cursor)
        tl.add_title(sentence.rstrip(".,;，；"), cursor, dur)
        cursor += dur + gap
    return cursor

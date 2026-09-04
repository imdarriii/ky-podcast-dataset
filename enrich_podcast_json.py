"""Add duration, text stats, and dataset fields to the_last/podcast.json."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "the_last"
SRC = ROOT / "podcast.json"
SAMPLE_RATE = 44100
CHANNELS = 1
BIT_DEPTH = 16
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * (BIT_DEPTH // 8)


def word_count(text: str) -> int:
    return len([w for w in text.split() if w])


def wav_bytes(path: Path, duration: float) -> int | None:
    if path.exists():
        return path.stat().st_size
    # PCM s16le mono header + samples (same as Colab export)
    return 44 + int(round(duration * SAMPLE_RATE)) * 2


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    clips = data["clips"]
    enriched = []
    speaker_secs: dict[str, float] = {}
    speaker_clips: dict[str, int] = {}

    for i, clip in enumerate(clips, start=1):
        start = float(clip["start_sec"])
        end = float(clip["end_sec"])
        duration = round(end - start, 2)
        text = (clip.get("text") or "").strip()
        rel = clip["audio"]
        wav = ROOT / rel
        size = wav_bytes(wav, duration)
        speaker = clip["speaker"]
        speaker_secs[speaker] = speaker_secs.get(speaker, 0.0) + duration
        speaker_clips[speaker] = speaker_clips.get(speaker, 0) + 1
        enriched.append({
            "id": i,
            "audio": rel,
            "filename": Path(rel).name,
            "speaker": speaker,
            "start_sec": round(start, 2),
            "end_sec": round(end, 2),
            "duration_sec": duration,
            "duration_ms": int(round(duration * 1000)),
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "bit_depth": BIT_DEPTH,
            "file_bytes": size,
            "text": text,
            "text_chars": len(text),
            "text_words": word_count(text),
        })

    total_sec = round(sum(c["duration_sec"] for c in enriched), 2)
    payload = {
        "id": "p3DNXhhp71w",
        "podcast": "p3DNXhhp71w",
        "title": "Сөздүн күчү",
        "youtube_url": "https://youtu.be/p3DNXhhp71w",
        "language": "ky",
        "source": data.get("audio"),
        "diarizer": data.get("diarizer"),
        "asr": data.get("asr"),
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "bit_depth": BIT_DEPTH,
        "num_speakers": len(speaker_clips),
        "num_clips": len(enriched),
        "duration_sec": total_sec,
        "duration_ms": int(round(total_sec * 1000)),
        "text_chars": sum(c["text_chars"] for c in enriched),
        "text_words": sum(c["text_words"] for c in enriched),
        "speakers": [
            {
                "speaker": name,
                "num_clips": speaker_clips[name],
                "duration_sec": round(speaker_secs[name], 2),
            }
            for name in sorted(speaker_clips)
        ],
        "clips": enriched,
    }
    SRC.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {SRC}")
    print(f"clips {payload['num_clips']} duration {payload['duration_sec']}s words {payload['text_words']}")
    for s in payload["speakers"]:
        print(f"  {s['speaker']}: {s['num_clips']} clips, {s['duration_sec']}s")


if __name__ == "__main__":
    main()

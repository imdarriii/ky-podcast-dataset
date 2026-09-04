"""Write one JSON next to every speaker clip, plus an index per speaker folder."""

from __future__ import annotations

import json
from pathlib import Path

import soundfile as sf

from diarize_podcast import parse_clip_times, write_dataset_json

SKIP = {"all_speech.wav"}


def clip_record(wav: Path, dataset: str) -> dict:
    text = ""
    txt = wav.with_suffix(".txt")
    if txt.exists():
        text = txt.read_text(encoding="utf-8").strip()
    start, end = parse_clip_times(wav.stem)
    info = sf.info(str(wav))
    duration = float(info.duration)
    if start is not None and end is not None:
        duration = round(end - start, 3)
    return {
        "audio": wav.name,
        "audio_path": f"{wav.parent.name}/{wav.name}",
        "folder": wav.parent.name,
        "dataset": dataset,
        "speaker": wav.parent.name,
        "start_sec": start,
        "end_sec": end,
        "duration_sec": duration,
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "language": "ky",
        "asr": "GigaAM-Multilingual large_ctc",
        "text": text,
        "has_text": bool(text),
    }


def write_folder(root: Path) -> None:
    dataset = root.name
    speaker_dirs = sorted(p for p in root.glob("SPEAKER_*") if p.is_dir())
    if not speaker_dirs:
        print(f"skip {root}: no SPEAKER_* folders")
        return
    total = 0
    with_text = 0
    for speaker_dir in speaker_dirs:
        records = []
        for wav in sorted(speaker_dir.glob("*.wav")):
            if wav.name in SKIP:
                continue
            rec = clip_record(wav, dataset)
            rec_path = wav.with_suffix(".json")
            rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            records.append(rec)
            total += 1
            with_text += int(rec["has_text"])
        index = {
            "dataset": dataset,
            "speaker": speaker_dir.name,
            "folder": str(speaker_dir.as_posix()),
            "language": "ky",
            "clips": records,
            "clip_count": len(records),
            "with_text": sum(1 for r in records if r["has_text"]),
        }
        (speaker_dir / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  {speaker_dir}: {len(records)} json + index.json")
    write_dataset_json(root, root / "podcast.json")
    print(f"{root.name}: {total} clips, {with_text} with text")


def main() -> None:
    root = Path(__file__).resolve().parent
    for name in ("speakers", "speakers (1)"):
        folder = root / name
        if folder.is_dir():
            print("===", folder.name, "===")
            write_folder(folder)


if __name__ == "__main__":
    main()

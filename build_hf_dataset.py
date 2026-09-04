"""Pack the_last into a Hugging Face-style dataset (same layout as Dialogs)."""
from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "the_last"
OUT = ROOT / "hf_ky_dialogs"
WAVS = OUT / "wavs"

SPEAKERS = {
    "SPEAKER_00": {
        "speaker_id": "N",
        "speaker_name": "Нуркыз Кадырбекова",
        "role": "guest",
        "gender": "F",
    },
    "SPEAKER_01": {
        "speaker_id": "G",
        "speaker_name": "Гүлзада Таалайбекова",
        "role": "host",
        "gender": "F",
    },
}

FIELDS = [
    "audio_path",
    "speaker_id",
    "speaker_name",
    "role",
    "gender",
    "language",
    "start_sec",
    "end_sec",
    "duration",
    "text",
    "text_words",
    "text_chars",
    "style",
    "sample_rate",
]


def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    data = json.loads((SRC / "podcast.json").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    WAVS.mkdir(exist_ok=True)

    rows = []
    for clip in data["clips"]:
        speaker = clip["speaker"]
        meta = SPEAKERS[speaker]
        src_wav = SRC / clip["audio"]
        if not src_wav.exists():
            raise SystemExit(f"missing wav: {src_wav}")
        dest_rel = f"wavs/{speaker}/{src_wav.name}"
        link_or_copy(src_wav, OUT / dest_rel)
        rows.append({
            "audio_path": dest_rel,
            "speaker_id": meta["speaker_id"],
            "speaker_name": meta["speaker_name"],
            "role": meta["role"],
            "gender": meta["gender"],
            "language": "ky",
            "start_sec": f"{clip['start_sec']:.2f}",
            "end_sec": f"{clip['end_sec']:.2f}",
            "duration": f"{clip['duration_sec']:.2f}",
            "text": clip["text"],
            "text_words": clip["text_words"],
            "text_chars": clip["text_chars"],
            "style": "conversational",
            "sample_rate": clip["sample_rate"],
        })

    for name in ("metadata.csv", "train.csv"):
        with (OUT / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="|")
            w.writeheader()
            w.writerows(rows)

    shutil.copy2(SRC / "podcast.json", OUT / "podcast.json")
    print(f"wrote {OUT}")
    print(f"rows {len(rows)} wavs {sum(1 for _ in WAVS.rglob('*.wav'))}")


if __name__ == "__main__":
    main()

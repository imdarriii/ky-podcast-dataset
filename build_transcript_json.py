"""Fill missing Kyrgyz texts with GigaAM and write one podcast.json.

Usage:
  python build_transcript_json.py output/p3DNXhhp71w
  python build_transcript_json.py output/p3DNXhhp71w --skip-asr
"""

from __future__ import annotations

import argparse
from pathlib import Path

from diarize_podcast import load_gigaam, transcribe_one, write_dataset_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Folder with SPEAKER_00 / SPEAKER_01")
    parser.add_argument("--skip-asr", action="store_true", help="Only pack existing .txt into JSON")
    parser.add_argument("--gigaam-variant", default="large_ctc", choices=["ctc", "large_ctc"])
    args = parser.parse_args()

    out_dir = Path(args.folder)
    wavs = [
        p for p in sorted(out_dir.glob("SPEAKER_*/*.wav"))
        if p.name != "all_speech.wav"
    ]
    if not wavs:
        raise SystemExit(f"No speaker clips in {out_dir}")

    model = None
    if not args.skip_asr:
        need = [
            w for w in wavs
            if not w.with_suffix(".txt").exists()
            or not w.with_suffix(".txt").read_text(encoding="utf-8").strip()
        ]
        if need:
            model = load_gigaam(args.gigaam_variant)
            for wav in need:
                text = transcribe_one(model, wav)
                wav.with_suffix(".txt").write_text(text, encoding="utf-8")
                preview = (text[:80] + "…") if len(text) > 80 else text
                print(f"    {wav.parent.name}/{wav.name}  {preview}")
        else:
            print("All clips already have text")

    write_dataset_json(out_dir)


if __name__ == "__main__":
    main()

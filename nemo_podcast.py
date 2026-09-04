"""YouTube/local podcast → NVIDIA NeMo diarization → speaker clips + GigaAM JSON.

Same post-steps as diarize_podcast.py, but speaker labels come from NeMo
ClusteringDiarizer instead of pyannote.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from diarize_podcast import (
    SAMPLE_RATE,
    convert_to_wav,
    download_youtube_audio,
    drop_isolated_bursts,
    ffmpeg_prefilter,
    get_speech_stamps,
    load_gigaam,
    mute_nonspeech_inplace,
    split_and_transcribe,
    stamps_to_seconds,
)


# Official NVIDIA config (Speech repo, same files as NVIDIA/NeMo).
CONFIG_URL = (
    "https://raw.githubusercontent.com/NVIDIA-NeMo/Speech/main/"
    "examples/speaker_tasks/diarization/conf/inference/diar_infer_meeting.yaml"
)


class RttmDiarization:
    def __init__(self, turns: list[dict]):
        self.turns = turns

    def itertracks(self, yield_label: bool = True):
        for t in self.turns:
            turn = type("Turn", (), {"start": t["start"], "end": t["end"]})()
            yield turn, None, t["speaker"]

    def write_rttm(self, f):
        for t in self.turns:
            dur = t["end"] - t["start"]
            f.write(
                f"SPEAKER file 1 {t['start']:.3f} {dur:.3f} "
                f"<NA> <NA> {t['speaker']} <NA> <NA>\n"
            )


def norm_speaker(label: str) -> str:
    raw = str(label)
    if raw.startswith("SPEAKER_"):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits:
        return f"SPEAKER_{int(digits):02d}"
    return raw


def parse_rttm(path: Path) -> list[dict]:
    turns = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        dur = float(parts[4])
        turns.append({
            "start": start,
            "end": start + dur,
            "speaker": norm_speaker(parts[7]),
        })
    turns.sort(key=lambda t: (t["start"], t["end"]))
    return turns


def find_pred_rttm(out_dir: Path) -> Path:
    hits = sorted(out_dir.rglob("*.rttm"))
    pred = [p for p in hits if "pred" in str(p).lower()]
    if pred:
        return pred[0]
    if hits:
        return hits[0]
    raise SystemExit(f"NeMo did not write an RTTM under {out_dir}")


def download_config(dst: Path) -> Path:
    bundled = Path(__file__).resolve().parent / "nemo_diar_infer.yaml"
    if bundled.exists() and bundled.stat().st_size > 100:
        shutil.copy2(bundled, dst)
        return dst
    if dst.exists() and dst.stat().st_size > 100:
        return dst
    try:
        import urllib.request
        urllib.request.urlretrieve(CONFIG_URL, dst)
    except Exception:
        alt = CONFIG_URL.replace("diar_infer_meeting.yaml", "diar_infer_telephonic.yaml")
        import urllib.request
        urllib.request.urlretrieve(alt, dst)
    return dst


def run_nemo(wav_path: Path, work: Path, num_speakers: int) -> Path:
    from omegaconf import OmegaConf
    try:
        from nemo.collections.asr.models import ClusteringDiarizer
    except ImportError:
        from nemo.collections.asr.models.msdd_models import ClusteringDiarizer

    nemo_dir = work / "nemo"
    nemo_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = download_config(nemo_dir / "diar_infer.yaml")
    cfg = OmegaConf.load(str(cfg_path))

    manifest = nemo_dir / "manifest.json"
    meta = {
        "audio_filepath": str(wav_path.resolve()),
        "offset": 0,
        "duration": None,
        "label": "infer",
        "text": "-",
        "num_speakers": num_speakers,
        "rttm_filepath": None,
        "uem_filepath": None,
    }
    manifest.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    cfg.num_workers = 1
    cfg.diarizer.manifest_filepath = str(manifest)
    cfg.diarizer.out_dir = str(nemo_dir / "out")
    cfg.diarizer.oracle_vad = False
    cfg.diarizer.vad.model_path = "vad_multilingual_marblenet"
    cfg.diarizer.speaker_embeddings.model_path = "titanet_large"
    cfg.diarizer.speaker_embeddings.parameters.save_embeddings = False
    cfg.diarizer.clustering.parameters.oracle_num_speakers = True

    print("[2/5] Official NVIDIA NeMo ClusteringDiarizer")
    print("      repo: https://github.com/NVIDIA/NeMo")
    print("      VAD:  vad_multilingual_marblenet")
    print("      emb:  titanet_large")
    model = ClusteringDiarizer(cfg=cfg)
    if hasattr(model, "to"):
        import torch
        if torch.cuda.is_available():
            model = model.to("cuda")
    model.diarize()
    rttm = find_pred_rttm(Path(cfg.diarizer.out_dir))
    print(f"      RTTM: {rttm}")
    return rttm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", help="YouTube URL or local audio file")
    parser.add_argument("--output", default="output/nemo_short")
    parser.add_argument("--num-speakers", type=int, default=2)
    parser.add_argument("--no-transcribe", action="store_true")
    args = parser.parse_args()

    if args.audio.startswith(("http://", "https://")):
        input_path = download_youtube_audio(args.audio)
    else:
        input_path = Path(args.audio)
        if not input_path.exists():
            sys.exit(f"File not found: {input_path}")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    wav = work / "audio_16k.wav"
    if not wav.exists() or wav.stat().st_size < 1000:
        convert_to_wav(input_path, wav)
        ffmpeg_prefilter(wav)
    else:
        print("[1/5] Resume: 16 kHz WAV already exists")

    vad_stamps = drop_isolated_bursts(get_speech_stamps(wav), SAMPLE_RATE)
    vad_times = stamps_to_seconds(vad_stamps, SAMPLE_RATE)
    if vad_stamps:
        mute_nonspeech_inplace(wav, vad_stamps)
    shutil.copy2(wav, out_dir / "cleaned_16k.wav")

    rttm = run_nemo(wav, work, args.num_speakers)
    turns = parse_rttm(rttm)
    if not turns:
        sys.exit("NeMo returned zero speaker turns")
    print(f"      turns: {len(turns)} speakers: {sorted({t['speaker'] for t in turns})}")

    diarization = RttmDiarization(turns)
    with open(out_dir / "diarization.rttm", "w", encoding="utf-8") as f:
        diarization.write_rttm(f)

    gigaam = None if args.no_transcribe else load_gigaam("large_ctc")
    split_and_transcribe(
        diarization,
        wav,
        out_dir,
        0.8, 1.0, 0.12, 0.45, 0.70,
        vad_times, 0.30,
        gigaam,
    )
    print(f"\nDone. Results in: {out_dir.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

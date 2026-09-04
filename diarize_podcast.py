"""
Podcast cleaner → speaker diarization → per-speaker clips + streaming Kyrgyz ASR.

This is the strongest local CPU stack for a speech dataset:

  1. Convert to 16 kHz mono.
  2. CLEAN FIRST (before any speaker split):
       ffmpeg  — rumble, hiss, mic thumps, stationary noise, clicks
       DeepFilterNet3 — room noise, fan, rustle (noisereduce if DF is missing)
       Demucs  — background song / music bed (adaptive, does not replace the voice)
       VAD     — mute leftover non-speech (jingle, taps, silence)
  3. Diarize the cleaned track.
  4. Merge same-speaker turns, snap to VAD, pad the ending so words are not cut.
  5. GigaAM transcribes each clip as soon as it is saved.

Nothing here is Krisp/iZotope. Those are closed and often a bit cleaner on
weird noise. Locally, this order is the real best: denoise → music → gate → diarize.

Usage:
  python diarize_podcast.py podcast.mp3 --num-speakers 2
  python diarize_podcast.py podcast.mp3 --num-speakers 2 --end 300
  python diarize_podcast.py podcast.mp3 --num-speakers 2 --no-demucs
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 16000
# GigaAM.transcribe() rejects anything over 25s; keep chunks under that.
MAX_SEGMENT_SECONDS = 24.0


def download_youtube_audio(url: str) -> Path:
    """Download YouTube audio in the native codec. Do not re-encode to MP3.

    YouTube already serves lossy Opus (usually format 251, ~160 kbps).
    Forcing --audio-format mp3 transcodes Opus→MP3 and adds robotic artifacts.
    Keep the original stream; decode once later with ffmpeg to WAV.
    """
    downloads = Path("downloads")
    downloads.mkdir(exist_ok=True)
    out_template = str(downloads / "%(id)s.%(ext)s")
    print(f"[0/5] Downloading native YouTube audio (no MP3 re-encode): {url}")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[acodec^=opus]/bestaudio/best",
        "--no-playlist",
        "--restrict-filenames",
        "--socket-timeout", "60",
        "--retries", "20",
        "--fragment-retries", "20",
        "--force-ipv4",
        "-o", out_template,
        "--print", "after_move:filepath",
        "--no-simulate",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stderr)
        sys.exit("yt-dlp failed to download the video audio")
    file_path = result.stdout.strip().splitlines()[-1]
    print(f"      Saved (native, no transcode): {file_path}")
    return Path(file_path)


def convert_to_wav(input_path: Path, wav_path: Path,
                   start: float = 0.0, end: float | None = None) -> None:
    print(f"[1/5] Converting {input_path.name} to 16 kHz mono WAV...")
    cmd = ["ffmpeg", "-y"]
    if start > 0:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += [
        "-i", str(input_path),
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stderr)
        sys.exit(f"ffmpeg failed to convert {input_path}")


def load_mono(wav_path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32), sr


def match_length(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) == n:
        return x
    if len(x) > n:
        return x[:n]
    return np.pad(x, (0, n - len(x)))


def peak_limit(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 1.0:
        audio = audio / peak * 0.99
    return audio.astype(np.float32)


def ffmpeg_prefilter(wav_path: Path) -> None:
    """Only cut rumble/mic thumps. No spectral denoise — that thins voices."""
    print("[1a/5] ffmpeg: highpass 70 Hz (rumble only, voice untouched)...")
    dst = wav_path.with_name("ffmpeg_clean.wav")
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_path),
        "-af", "highpass=f=70", "-c:a", "pcm_s16le", str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode == 0:
        shutil.move(str(dst), str(wav_path))
        return
    print(result.stderr)
    print("      warning: ffmpeg highpass failed, continuing with raw audio")
    dst.unlink(missing_ok=True)


def denoise_deepfilter(wav_path: Path) -> bool:
    """DeepFilterNet3 with a dry-voice mix so speaker timbre stays."""
    try:
        from deepfilter_stream import Denoiser
    except ImportError:
        return False

    # atten_lim_db=8 ≈ 40% original voice always kept. Full DF would sound "processed".
    print("[1b/5] DeepFilterNet3: noise only, original voice mixed back...")
    audio, sr = load_mono(wav_path)
    denoiser = Denoiser(atten_lim_db=8)
    hop = sr * 30
    parts: list[np.ndarray] = []
    for i in range(0, len(audio), hop):
        parts.append(denoiser.process(audio[i:i + hop], sr))
        done = min(i + hop, len(audio)) / sr
        print(f"      {done:.0f}s / {len(audio) / sr:.0f}s", flush=True)
    tail = denoiser.flush()
    if tail.size:
        parts.append(tail)
    out = peak_limit(match_length(np.concatenate(parts), len(audio)))
    sf.write(str(wav_path), out, sr)
    print("      DeepFilterNet done (voice-safe)")
    return True


def denoise_noisereduce(wav_path: Path) -> bool:
    try:
        import noisereduce as nr
    except ImportError:
        return False
    print("[1b/5] noisereduce fallback, mild (prop=0.45)...")
    audio, sr = load_mono(wav_path)
    out = nr.reduce_noise(y=audio, sr=sr, stationary=True, prop_decrease=0.45)
    sf.write(str(wav_path), peak_limit(out.astype(np.float32)), sr)
    return True


def extract_vocals_and_acc(wav_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Demucs vocals + leftover music bed. Voice is not replaced yet."""
    print("[1c/5] Demucs: separate music bed from speech (slow on CPU)...")
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio
    from demucs.pretrained import get_model

    model = get_model("htdemucs")
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)

    original, sr = load_mono(wav_path)
    wav = torch.from_numpy(np.stack([original, original])).float()
    wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)

    with torch.no_grad():
        sources = apply_model(
            model,
            wav[None],
            device=device,
            split=True,
            overlap=0.25,
            progress=True,
        )[0]

    vocals = sources[model.sources.index("vocals")]
    vocals = convert_audio(vocals, model.samplerate, sr, 1).squeeze(0).cpu().numpy()
    n = min(len(vocals), len(original))
    original = original[:n]
    vocals = vocals[:n]
    acc = original - vocals
    print("      music bed estimated")
    return original, vocals, acc


def adaptive_remove_music(original: np.ndarray, vocals: np.ndarray, acc: np.ndarray,
                          sr: int, music_skip: float) -> np.ndarray:
    """Never replace the speaker with Demucs 'vocals'. That stem sounds fake.

    Speech windows keep the original waveform; only a fraction of the music
    bed is subtracted. Song-only windows are muted.
    """
    hop = int(0.25 * sr)
    n = len(original)
    out = np.empty(n, dtype=np.float32)
    muted = 0
    for i in range(0, n, hop):
        j = min(i + hop, n)
        acc_e = float(np.mean(acc[i:j] ** 2))
        voc_e = float(np.mean(vocals[i:j] ** 2))
        share = acc_e / (acc_e + voc_e + 1e-9)
        if share >= music_skip and voc_e < 0.0015:
            out[i:j] = 0
            muted += 1
        elif share >= 0.45:
            # more music under talk: subtract more bed, still the same voice
            reduce = 0.25 + 0.20 * float(np.clip((share - 0.45) / 0.40, 0.0, 1.0))
            out[i:j] = original[i:j] - reduce * acc[i:j]
        else:
            out[i:j] = original[i:j]
    print(f"      music bed subtracted from original voice; muted {muted} song-only windows")
    return peak_limit(out)


def suppress_impulses(audio: np.ndarray, sr: int) -> np.ndarray:
    """Attenuate isolated mic-tap / chair clicks. Leaves speech plosives alone."""
    hop = max(1, int(0.004 * sr))
    n = len(audio) // hop
    if n < 8:
        return audio
    peaks = np.abs(audio[:n * hop]).reshape(n, hop).max(axis=1)
    kernel = max(5, int(0.08 * sr / hop))
    pad = kernel // 2
    padded = np.pad(peaks, pad, mode="edge")
    med = np.array([np.median(padded[i:i + kernel]) for i in range(n)], dtype=np.float32)
    click = (peaks > 14.0 * (med + 1e-6)) & (med < 0.025)
    if not np.any(click):
        return audio
    out = audio.copy()
    for idx in np.flatnonzero(click):
        a = idx * hop
        b = min(len(out), a + hop)
        out[a:b] *= 0.08
    print(f"      suppressed {int(click.sum())} click frames")
    return out


def enhance_podcast(wav_path: Path, do_denoise: bool, do_demucs: bool,
                    music_skip: float) -> None:
    """Full cleanup. Checkpoints stay on disk so a crash can resume."""
    work = wav_path.parent
    denoised_mark = work / "denoised_16k.wav"
    enhanced_mark = work / "enhanced_16k.wav"

    if enhanced_mark.exists() and enhanced_mark.stat().st_size > 1000:
        shutil.copy2(enhanced_mark, wav_path)
        print("[1/5] Resume: enhanced track already saved, skip cleanup")
        return

    if denoised_mark.exists() and denoised_mark.stat().st_size > 1000:
        shutil.copy2(denoised_mark, wav_path)
        print("[1/5] Resume: denoised checkpoint found, skip DeepFilterNet")
    else:
        print("[1/5] Cleaning the podcast BEFORE diarization...")
        ffmpeg_prefilter(wav_path)
        if do_denoise:
            if not denoise_deepfilter(wav_path):
                if not denoise_noisereduce(wav_path):
                    print("      no DeepFilterNet/noisereduce, ffmpeg-only denoise")
        audio, sr = load_mono(wav_path)
        sf.write(str(denoised_mark), audio, sr)
        print(f"      checkpoint saved: {denoised_mark.name}")

    if do_demucs:
        original, vocals, acc = extract_vocals_and_acc(wav_path)
        cleaned = adaptive_remove_music(original, vocals, acc, SAMPLE_RATE, music_skip)
        sf.write(str(wav_path), cleaned, SAMPLE_RATE)
    audio, sr = load_mono(wav_path)
    audio = suppress_impulses(audio, sr)
    sf.write(str(wav_path), peak_limit(audio), sr)
    shutil.copy2(wav_path, enhanced_mark)
    print("      clean track ready")


def get_speech_stamps(wav_path: Path, pad_ms: int = 500) -> list[dict]:
    """Silero VAD timestamps in samples."""
    print("[1d/5] Silero VAD: keep speech, drop leftover noise/music...")
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    audio, sr = load_mono(wav_path)
    model = load_silero_vad()
    stamps = get_speech_timestamps(
        torch.from_numpy(audio),
        model,
        sampling_rate=sr,
        threshold=0.30,
        min_speech_duration_ms=80,
        min_silence_duration_ms=350,
        speech_pad_ms=pad_ms,
    )
    speech_sec = sum((s["end"] - s["start"]) / sr for s in stamps)
    print(f"      VAD speech: {speech_sec:.0f}s / {len(audio) / sr:.0f}s")
    return stamps


def drop_isolated_bursts(stamps: list[dict], sr: int,
                         max_ms: int = 120, join_ms: int = 350) -> list[dict]:
    """Drop short islands far from real speech (mic tap, chair). Keep nearby 'да'."""
    if not stamps:
        return stamps
    join = int(join_ms * sr / 1000)
    merged = [dict(stamps[0])]
    for s in stamps[1:]:
        if s["start"] - merged[-1]["end"] <= join:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(dict(s))
    min_len = int(max_ms * sr / 1000)
    kept = [s for s in merged if (s["end"] - s["start"]) >= min_len]
    dropped = len(merged) - len(kept)
    if dropped:
        print(f"      dropped {dropped} isolated non-speech bursts")
    return kept


def stamps_to_seconds(stamps: list[dict], sr: int) -> list[tuple[float, float]]:
    return [(s["start"] / sr, s["end"] / sr) for s in stamps]


def mute_nonspeech_inplace(wav_path: Path, stamps: list[dict]) -> None:
    audio, sr = load_mono(wav_path)
    keep = np.zeros_like(audio)
    for seg in stamps:
        keep[seg["start"]:seg["end"]] = audio[seg["start"]:seg["end"]]
    sf.write(str(wav_path), keep, sr)
    muted = (len(audio) - sum(s["end"] - s["start"] for s in stamps)) / sr
    print(f"      muted {muted:.0f}s of leftover non-speech on the clean track")


def first_sustained_speech(vad_times: list[tuple[float, float]],
                           min_speech: float = 2.0,
                           max_search: float = 90.0) -> float:
    for start, end in vad_times:
        if start > max_search:
            break
        if end - start >= min_speech:
            return start
    return 0.0


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def speech_coverage(start: float, end: float,
                    vad_times: list[tuple[float, float]]) -> float:
    covered = sum(interval_overlap(start, end, s, e) for s, e in vad_times)
    return covered / max(end - start, 1e-6)


def collect_turns(diarization) -> list[dict]:
    turns = []
    if hasattr(diarization, "itertracks"):
        tracks = diarization.itertracks(yield_label=True)
        for turn, _, speaker in tracks:
            turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
    else:
        # Official README: for turn, speaker in output.speaker_diarization
        for turn, speaker in diarization:
            turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
    turns.sort(key=lambda t: (t["start"], t["end"]))
    return turns


def merge_same_speaker(turns: list[dict], max_gap: float) -> list[dict]:
    if not turns:
        return []
    merged = [dict(turns[0])]
    for t in turns[1:]:
        prev = merged[-1]
        gap = t["start"] - prev["end"]
        if t["speaker"] == prev["speaker"] and 0 <= gap <= max_gap:
            prev["end"] = max(prev["end"], t["end"])
        else:
            merged.append(dict(t))
    return merged


def snap_to_vad(turns: list[dict], vad_times: list[tuple[float, float]],
                max_extend: float) -> list[dict]:
    if not vad_times or max_extend <= 0:
        return turns
    out = []
    for i, t in enumerate(turns):
        start, end = t["start"], t["end"]
        for vs, ve in vad_times:
            if ve < start or vs > end:
                continue
            start = min(start, vs) if start - vs <= max_extend else start
            end = max(end, ve) if ve - end <= max_extend else end
        if i > 0 and turns[i - 1]["speaker"] != t["speaker"]:
            start = max(start, turns[i - 1]["end"] - 0.04)
        if i + 1 < len(turns) and turns[i + 1]["speaker"] != t["speaker"]:
            end = min(end, turns[i + 1]["start"] + 0.04)
        if end > start:
            out.append({**t, "start": start, "end": end})
    return out


def add_collar(turns: list[dict], start_pad: float, end_pad: float,
               audio_dur: float) -> list[dict]:
    out = []
    for i, t in enumerate(turns):
        start = max(0.0, t["start"] - start_pad)
        end = min(audio_dur, t["end"] + end_pad)
        if i > 0 and turns[i - 1]["speaker"] != t["speaker"]:
            start = max(start, turns[i - 1]["end"] - 0.05)
        if i + 1 < len(turns) and turns[i + 1]["speaker"] != t["speaker"]:
            end = min(end, turns[i + 1]["start"] + 0.05)
        if end > start:
            out.append({**t, "start": start, "end": end})
    return out


def find_silence_near(vad_times: list[tuple[float, float]],
                      target: float, window: float, earliest: float) -> float | None:
    best = None
    best_dist = window + 1
    prev_end = earliest
    for vs, ve in vad_times:
        gap_start, gap_end = prev_end, vs
        prev_end = max(prev_end, ve)
        if gap_end <= earliest or gap_start >= target + window:
            continue
        mid = 0.5 * (max(gap_start, earliest) + min(gap_end, target + window))
        if abs(mid - target) < best_dist and mid > earliest:
            best, best_dist = mid, abs(mid - target)
    return best


def split_long_turn(start: float, end: float,
                    vad_times: list[tuple[float, float]],
                    max_len: float = MAX_SEGMENT_SECONDS,
                    min_chunk: float = 1.2) -> list[tuple[float, float]]:
    if end - start <= max_len:
        return [(start, end)]
    chunks = []
    cur = start
    while cur < end - 1e-3:
        target = min(cur + max_len, end)
        if target >= end - 0.05:
            chunks.append((cur, end))
            break
        split_at = find_silence_near(vad_times, target, window=3.0, earliest=cur + min_chunk)
        if split_at is None or split_at <= cur + min_chunk:
            split_at = target
        chunks.append((cur, min(split_at, end)))
        cur = min(split_at, end)
    return chunks


def export_clip(audio: np.ndarray, start: float, end: float) -> np.ndarray | None:
    start_i = max(0, int(start * SAMPLE_RATE))
    end_i = min(len(audio), int(end * SAMPLE_RATE))
    if end_i <= start_i:
        return None
    clip = audio[start_i:end_i].astype(np.float32)
    if float(np.sqrt(np.mean(clip ** 2))) < 0.003:
        return None
    return clip


def run_diarization(wav_path: Path, hf_token: str, num_speakers: int | None):
    """Official pyannote-audio community-1 pipeline (github.com/pyannote/pyannote-audio)."""
    print("[2/5] Loading pyannote from GitHub toolkit (speaker-diarization-community-1)...")
    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token,
    )
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))

    print("[2/5] Running diarization on the CLEAN track...")
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers

    # Waveform dict avoids torchcodec path issues on Windows (same result as pipeline(wav)).
    audio, sr = load_mono(wav_path)
    waveform = torch.from_numpy(audio).unsqueeze(0)
    audio_input = {"waveform": waveform, "sample_rate": sr}

    with ProgressHook() as hook:
        output = pipeline(audio_input, hook=hook, **kwargs)

    # Official README: output.speaker_diarization
    # exclusive_* avoids overlapping the same time into two speaker folders
    for attr in ("exclusive_speaker_diarization", "speaker_diarization"):
        if hasattr(output, attr):
            return getattr(output, attr)
    return output


def load_gigaam(variant: str):
    print(f"[4/5] Loading GigaAM-Multilingual ({variant})...")
    from transformers import AutoModel

    local_dir = Path("models") / f"gigaam_{variant}"
    if local_dir.is_dir() and (local_dir / "pytorch_model.bin").exists():
        model = AutoModel.from_pretrained(str(local_dir), trust_remote_code=True)
    else:
        model = AutoModel.from_pretrained(
            "ai-sage/GigaAM-Multilingual",
            revision=variant,
            trust_remote_code=True,
        )
    print("      GigaAM ready — each clip is transcribed as soon as it is saved")
    return model


def _result_to_text(result) -> str:
    if result is None:
        return ""
    if hasattr(result, "text"):
        return (result.text or "").strip()
    return str(result).strip()


def transcribe_chunked(model, clip_path: Path, max_sec: float = 24.0) -> str:
    """Split a long clip and transcribe each piece. No pyannote longform needed."""
    audio, sr = load_mono(clip_path)
    hop = int(max_sec * sr)
    parts: list[str] = []
    tmp_dir = clip_path.parent
    for i in range(0, len(audio), hop):
        chunk = audio[i:i + hop]
        if len(chunk) < int(0.4 * sr):
            continue
        tmp = tmp_dir / f".tmp_{clip_path.stem}_{i}.wav"
        sf.write(str(tmp), chunk, sr)
        try:
            parts.append(_result_to_text(model.transcribe(str(tmp))))
        except Exception as e:
            print(f"    warning: chunk failed on {clip_path.name}: {e}")
        finally:
            tmp.unlink(missing_ok=True)
    return " ".join(p for p in parts if p)


def transcribe_one(model, clip_path: Path) -> str:
    """Short clips use transcribe(); longer ones are split into 24s chunks."""
    try:
        return _result_to_text(model.transcribe(str(clip_path)))
    except Exception as e:
        msg = str(e)
        if "longform" not in msg.lower() and "Too long" not in msg:
            print(f"    warning: failed on {clip_path.name}: {e}")
            return ""
    try:
        text = _result_to_text(model.transcribe_longform(str(clip_path)))
        if text:
            return text
    except Exception:
        pass
    return transcribe_chunked(model, clip_path)


def split_and_transcribe(
    diarization,
    clean_wav: Path,
    out_dir: Path,
    min_duration: float,
    merge_gap: float,
    start_pad: float,
    end_pad: float,
    vad_extend: float,
    vad_times: list[tuple[float, float]],
    min_speech_ratio: float,
    gigaam_model,
):
    print("[3/5] Cutting full utterances from the clean track...")
    audio, sr = load_mono(clean_wav)
    assert sr == SAMPLE_RATE
    audio_dur = len(audio) / sr

    raw = collect_turns(diarization)
    merged = merge_same_speaker(raw, merge_gap)
    snapped = snap_to_vad(merged, vad_times, vad_extend)
    padded = add_collar(snapped, start_pad, end_pad, audio_dur)
    print(
        f"      turns: {len(raw)} raw → {len(merged)} merged → {len(padded)} after VAD/pad"
    )

    csv_path = out_dir / "transcript.csv"
    txt_path = out_dir / "transcript.txt"
    csv_file = open(csv_path, "w", newline="", encoding="utf-8-sig")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["speaker", "start_sec", "end_sec", "duration", "file", "text"])
    txt_file = open(txt_path, "w", encoding="utf-8")

    segments = []
    counters: dict[str, int] = {}
    skipped = 0
    durations: dict[str, list[float]] = {}

    try:
        for turn in padded:
            speaker = turn["speaker"]
            for chunk_start, chunk_end in split_long_turn(
                turn["start"], turn["end"], vad_times
            ):
                duration = chunk_end - chunk_start
                if duration < min_duration:
                    continue
                if vad_times and speech_coverage(chunk_start, chunk_end, vad_times) < min_speech_ratio:
                    skipped += 1
                    continue

                clip = export_clip(audio, chunk_start, chunk_end)
                if clip is None:
                    skipped += 1
                    continue

                speaker_dir = out_dir / speaker
                speaker_dir.mkdir(parents=True, exist_ok=True)
                counters[speaker] = counters.get(speaker, 0) + 1
                name = f"{counters[speaker]:04d}_{chunk_start:08.2f}-{chunk_end:08.2f}.wav"
                clip_path = speaker_dir / name
                sf.write(str(clip_path), clip, SAMPLE_RATE)
                durations.setdefault(speaker, []).append(duration)

                text = ""
                if gigaam_model is not None:
                    text = transcribe_one(gigaam_model, clip_path)
                    clip_path.with_suffix(".txt").write_text(text, encoding="utf-8")
                    preview = (text[:80] + "…") if len(text) > 80 else text
                    print(
                        f"    {speaker} {counters[speaker]:04d}  "
                        f"{chunk_start:.2f}-{chunk_end:.2f}s ({duration:.1f}s)  {preview}"
                    )
                elif counters[speaker] % 10 == 0:
                    print(f"    {speaker}: {counters[speaker]} clips")

                csv_writer.writerow((
                    speaker, f"{chunk_start:.2f}", f"{chunk_end:.2f}",
                    f"{duration:.2f}", clip_path.name, text,
                ))
                csv_file.flush()
                txt_file.write(f"[{chunk_start:.2f}s - {chunk_end:.2f}s] {speaker}: {text}\n")
                txt_file.flush()
                segments.append((speaker, chunk_start, chunk_end, clip_path, text))
    finally:
        csv_file.close()
        txt_file.close()

    if skipped:
        print(f"      skipped {skipped} music/silence clips")

    for speaker in sorted(counters):
        speaker_dir = out_dir / speaker
        clips = sorted(p for p in speaker_dir.glob("*.wav") if p.name != "all_speech.wav")
        if clips:
            parts = [sf.read(str(p), dtype="float32")[0] for p in clips]
            sf.write(str(speaker_dir / "all_speech.wav"), np.concatenate(parts), SAMPLE_RATE)
        ds = durations.get(speaker, [])
        median = float(np.median(ds)) if ds else 0.0
        total = float(sum(ds))
        print(
            f"    {speaker}: {counters[speaker]} clips, "
            f"{total / 60:.1f} min, median {median:.1f}s + all_speech.wav"
        )
    write_dataset_json(out_dir)
    return segments


def parse_clip_times(stem: str) -> tuple[float | None, float | None]:
    try:
        span = stem.split("_", 1)[1]
        start_s, end_s = span.split("-")
        return float(start_s), float(end_s)
    except (IndexError, ValueError):
        return None, None


def write_dataset_json(out_dir: Path, json_path: Path | None = None) -> Path:
    """One JSON: audio filename + Kyrgyz text for every speaker clip."""
    clips = []
    for wav in sorted(out_dir.glob("SPEAKER_*/*.wav")):
        if wav.name == "all_speech.wav":
            continue
        txt_path = wav.with_suffix(".txt")
        text = txt_path.read_text(encoding="utf-8").strip() if txt_path.exists() else ""
        start, end = parse_clip_times(wav.stem)
        clips.append({
            "audio": f"{wav.parent.name}/{wav.name}",
            "speaker": wav.parent.name,
            "start_sec": start,
            "end_sec": end,
            "text": text,
        })
    payload = {
        "podcast": out_dir.name,
        "language": "ky",
        "asr": "GigaAM-Multilingual large_ctc",
        "clips": clips,
    }
    dest = json_path or (out_dir / "podcast.json")
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    empty = sum(1 for c in clips if not c["text"])
    print(f"      JSON: {dest} ({len(clips)} clips, {empty} empty texts)")
    return dest


def resolve_hf_token(cli_token: str | None) -> str:
    hf_token = cli_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not hf_token:
        try:
            from huggingface_hub import get_token
            hf_token = get_token()
        except ImportError:
            pass
    if not hf_token:
        sys.exit(
            "HuggingFace token required.\n"
            "1. Accept conditions: https://huggingface.co/pyannote/speaker-diarization-community-1\n"
            "2. Create a token:    https://huggingface.co/settings/tokens\n"
            "3. Run again with --hf-token hf_xxx  (or set the HF_TOKEN environment variable)"
        )
    return hf_token


def main():
    parser = argparse.ArgumentParser(
        description="Clean a podcast, then diarize and transcribe speaker clips."
    )
    parser.add_argument("audio", help="Path to the podcast audio file or a YouTube URL")
    parser.add_argument("--output", default=None, help="Output directory (default: output/<audio name>)")
    parser.add_argument("--hf-token", default=None, help="HuggingFace token (or set HF_TOKEN env var)")
    parser.add_argument("--num-speakers", type=int, default=None, help="Exact number of speakers, if known")
    parser.add_argument("--min-duration", type=float, default=0.8,
                        help="Skip segments shorter than this after merge (seconds)")
    parser.add_argument("--merge-gap", type=float, default=1.0,
                        help="Merge consecutive same-speaker turns if the gap is <= this")
    parser.add_argument("--start-pad", type=float, default=0.12,
                        help="Seconds to keep before a turn so the first word is not cut")
    parser.add_argument("--end-pad", type=float, default=0.45,
                        help="Seconds to keep after a turn so the last word is not cut")
    parser.add_argument("--vad-extend", type=float, default=0.70,
                        help="Max seconds to extend a turn to the VAD speech boundary")
    parser.add_argument("--min-speech-ratio", type=float, default=0.30,
                        help="Drop a clip if this fraction is not VAD speech")
    parser.add_argument("--start", type=float, default=0.0,
                        help="Skip everything before this time in seconds")
    parser.add_argument("--end", type=float, default=None,
                        help="Stop processing at this time in seconds")
    parser.add_argument("--auto-skip-intro", action="store_true", default=True,
                        help="Skip opening music until the first sustained speech")
    parser.add_argument("--no-auto-skip-intro", dest="auto_skip_intro", action="store_false")
    parser.add_argument("--clean", dest="clean", action="store_true", default=True,
                        help="Clean noise/music BEFORE diarization (default on)")
    parser.add_argument("--no-clean", dest="clean", action="store_false",
                        help="Skip the cleanup stage")
    parser.add_argument("--denoise", dest="denoise", action="store_true", default=True,
                        help="DeepFilterNet / noisereduce (default on)")
    parser.add_argument("--no-denoise", dest="denoise", action="store_false")
    parser.add_argument("--demucs", dest="demucs", action="store_true", default=True,
                        help="Remove background music with Demucs (default on, slow on CPU)")
    parser.add_argument("--no-demucs", dest="demucs", action="store_false",
                        help="Skip Demucs (faster; music under speech will remain)")
    parser.add_argument("--music-skip", type=float, default=0.78,
                        help="Mute a window if this share of energy is music")
    parser.add_argument("--no-vad", action="store_true",
                        help="Do not mute leftover non-speech with Silero VAD")
    parser.add_argument("--transcribe", dest="transcribe", action="store_true", default=True)
    parser.add_argument("--no-transcribe", dest="transcribe", action="store_false")
    parser.add_argument("--gigaam-variant", default="large_ctc", choices=["ctc", "large_ctc"])
    args = parser.parse_args()

    if args.audio.startswith(("http://", "https://")):
        input_path = download_youtube_audio(args.audio)
    else:
        input_path = Path(args.audio)
        if not input_path.exists():
            sys.exit(f"File not found: {input_path}")

    hf_token = resolve_hf_token(args.hf_token)

    out_dir = Path(args.output) if args.output else Path("output") / input_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    raw_wav = work / "raw_16k.wav"
    clean_wav = work / "current_16k.wav"
    if not raw_wav.exists() or raw_wav.stat().st_size < 1000:
        convert_to_wav(input_path, raw_wav, start=args.start, end=args.end)
    else:
        print("[1/5] Resume: raw 16 kHz WAV already exists")
    shutil.copy2(raw_wav, clean_wav)

    if args.clean:
        enhance_podcast(clean_wav, args.denoise, args.demucs, args.music_skip)
    else:
        print("[1/5] Cleanup off (--no-clean)")

    vad_stamps: list[dict] = []
    vad_times: list[tuple[float, float]] = []
    if not args.no_vad:
        vad_stamps = get_speech_stamps(clean_wav)
        vad_stamps = drop_isolated_bursts(vad_stamps, SAMPLE_RATE)
        vad_times = stamps_to_seconds(vad_stamps, SAMPLE_RATE)
        if args.auto_skip_intro and args.start <= 0:
            intro_end = first_sustained_speech(vad_times)
            if intro_end >= 1.5:
                print(f"      auto-skip intro: first {intro_end:.1f}s")
                audio, sr = load_mono(clean_wav)
                cut = int(intro_end * sr)
                sf.write(str(clean_wav), audio[cut:], sr)
                vad_stamps = [
                    {"start": max(0, s["start"] - cut), "end": max(0, s["end"] - cut)}
                    for s in vad_stamps
                    if s["end"] > cut
                ]
                vad_times = stamps_to_seconds(vad_stamps, SAMPLE_RATE)
        if vad_stamps:
            mute_nonspeech_inplace(clean_wav, vad_stamps)

    shutil.copy2(clean_wav, out_dir / "cleaned_16k.wav")
    print(f"      saved {out_dir / 'cleaned_16k.wav'}")

    diarization = run_diarization(clean_wav, hf_token, args.num_speakers)

    with open(out_dir / "diarization.rttm", "w", encoding="utf-8") as f:
        diarization.write_rttm(f)

    gigaam_model = load_gigaam(args.gigaam_variant) if args.transcribe else None
    if not args.transcribe:
        print("[4/5] Skipping transcription")

    split_and_transcribe(
        diarization,
        clean_wav,
        out_dir,
        args.min_duration,
        args.merge_gap,
        args.start_pad,
        args.end_pad,
        args.vad_extend,
        vad_times,
        args.min_speech_ratio,
        gigaam_model,
    )

    print(f"\nDone. Results in: {out_dir.resolve()}")


if __name__ == "__main__":
    main()

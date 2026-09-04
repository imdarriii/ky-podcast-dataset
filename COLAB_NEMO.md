# NVIDIA NeMo + чистый YouTube-звук

Диаризация не меняет голос. Робот шёл от `--audio-format mp3` (Opus → MP3).  
Скачиваем родной Opus, один раз декодируем в WAV.

## GitHub NVIDIA

- https://github.com/NVIDIA/NeMo
- https://github.com/NVIDIA-NeMo/Speech
- Конфиг: https://github.com/NVIDIA-NeMo/Speech/blob/main/examples/speaker_tasks/diarization/conf/inference/diar_infer_meeting.yaml

Модели: `vad_multilingual_marblenet` + `titanet_large` + `ClusteringDiarizer`

## Скачивание

```
yt-dlp -f "bestaudio[acodec^=opus]/bestaudio/best" URL
```

Без `--extract-audio --audio-format mp3`.

Потом два WAV из одного файла:

- `podcast_16k.wav` — только для NeMo
- `podcast_hq.wav` — 44.1 kHz, из него режем клипы

## Colab

Открой `colab_nemo.ipynb`, Runtime → T4 GPU, гони ячейки сверху вниз.  
Ничего заливать не нужно: ячейка 3 сама качает `https://youtu.be/p3DNXhhp71w`.

Если YouTube в Colab заблокирует — скачай локально тем же флагом и залей файл в Files.

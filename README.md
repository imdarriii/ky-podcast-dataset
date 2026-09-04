# Kyrgyz podcast speech dataset

Разговорный кыргызский: диаризация NVIDIA NeMo, текст GigaAM, сайт с прослушиванием и скачиванием JSON/папки.

## Что уже сделано (подкаст 1)

Источник: [youtu.be/p3DNXhhp71w](https://youtu.be/p3DNXhhp71w) — «Сөздүн күчү».

| | |
|---|---|
| Спикеры | 2: Нуркыз Кадырбекова (`SPEAKER_00`), Гүлзада Таалайбекова (`SPEAKER_01`) |
| Клипы | 31 целая реплика (не нарезка по 24 с) |
| Звук | родной YouTube, один decode в WAV 44.1 kHz mono, **без MP3 и без денoise** |
| Диаризация | официальный NVIDIA NeMo `ClusteringDiarizer` |
| ASR | GigaAM-Multilingual `large_ctc` |
| Готовые файлы | `the_last/` (wav + `podcast.json`), сайт в `web/` |
| Папка wav+JSON | https://gofile.io/d/xtMjPGvw |

Сайт (`web/`): клипы, фильтр по спикеру, скачать JSON, скачать папку.

## Как мы это делали (тот же процесс, что в Colab)

Ноутбук: `colab_nemo.ipynb`. Runtime → **T4 GPU**. Ячейки сверху вниз.

### 1. Скачать звук

```text
yt-dlp -f "bestaudio[acodec^=opus]/bestaudio/best" --no-playlist --restrict-filenames
  --extractor-args "youtube:player_client=android,tv,web"
  -o "native.%(ext)s" URL
```

**Нельзя** `--extract-audio --audio-format mp3`. Opus→MP3 даёт роботический голос. Это не баг диаризации.

### 2. Два WAV из одного файла

```text
ffmpeg -y -i native.* -ac 1 -ar 16000 -c:a pcm_s16le podcast_16k.wav   # только для NeMo
ffmpeg -y -i native.* -ac 1 -ar 44100 -c:a pcm_s16le podcast_hq.wav    # из этого режем клипы
```

Без DeepFilterNet, Demucs, спектральной чистки.

### 3. NVIDIA NeMo

Репозитории: [NVIDIA/NeMo](https://github.com/NVIDIA/NeMo), [NVIDIA-NeMo/Speech](https://github.com/NVIDIA-NeMo/Speech).

Конфиг: `examples/speaker_tasks/diarization/conf/inference/diar_infer_meeting.yaml`

- VAD: `vad_multilingual_marblenet`
- эмбеддинги: `titanet_large`
- `num_speakers=2`
- `oracle_num_speakers=True`

### 4. Склеить реплики и нарезать

- `MERGE_GAP = 3.0` — соседние куски одного спикера склеить
- `MIN_SEC = 0.8`
- один wav на целую реплику
- резать **из 44.1 kHz**, не из 16 kHz
- 24 секунды — только внутренний чанк ASR, не размер файла

### 5. GigaAM

```python
from transformers import AutoModel
asr = AutoModel.from_pretrained(
    "ai-sage/GigaAM-Multilingual", revision="large_ctc", trust_remote_code=True
)
```

Не Whisper. Текст не выдумывать: если ASR упал — пустая строка.

### 6. JSON

Как `the_last/podcast.json`: `id`, `title`, `youtube_url`, `language=ky`, спикеры, клипы с `audio`, таймкодами, `text`, размерами файла.

## Облачный агент: подкаст 2 + обновить сайт

Следующий ролик (ровно этот, 2 спикера):

**https://youtu.be/h1615IhITQ4**

Сделай **тот же Colab-процесс**, затем встрой результат в сайт.

### Выходные папки

```text
podcasts/h1615IhITQ4/
  podcast.json          # enriched, как the_last/podcast.json
  SPEAKER_00/*.wav
  SPEAKER_01/*.wav

web/podcasts/h1615IhITQ4/
  podcast.json          # копия enriched
  audio/SPEAKER_00/*.opus
  audio/SPEAKER_01/*.opus
```

Opus для сайта: `ffmpeg -i clip.wav -c:a libopus -b:a 96k clip.opus`

### Обновить витрину

1. Добавь запись в `web/catalog.json` (id `h1615IhITQ4`, title из yt-dlp, json/audio пути, имена спикеров если видны из текста, иначе оставь SPEAKER_00/01).
2. Не затирай подкаст `p3DNXhhp71w` и `web/podcast.json` / `web/audio/` первого выпуска.
3. На сайте должен переключаться выпуск, играть клипы, скачиваться JSON этого выпуска.
4. Папку wav+JSON второго выпуска положи в `podcasts/h1615IhITQ4/` и при возможности залей zip (Gofile или рядом, если файл &lt; 100 МБ). Ссылку пропиши в `catalog.json` → `folder_zip`.
5. Если доступен GitHub Pages — задеплой `web/` (Settings → Pages → folder `web`, или `gh-pages`). Напиши итоговый URL.

Нужен GPU. Если CUDA нет — всё равно тот же пайплайн на CPU, без фейковой диаризации. Если YouTube блокирует скачивание — те же `player_client`, не перекодировать в MP3.

## Локальные скрипты

- `colab_nemo.ipynb` — канон, то же что в Colab
- `nemo_podcast.py` — NeMo обёртка
- `enrich_podcast_json.py` — поля датасета в JSON
- `diarize_podcast.py` — старый локальный стек (pyannote + чистка). Для этих выпусков **не использовать**: чистка портит тембр, канон — сырой YouTube + NeMo.

## Права

Аудио принадлежит авторам роликов. Это витрина разметки, не открытый корпус без согласия.

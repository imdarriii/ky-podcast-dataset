---
language:
- ky
pretty_name: "Kyrgyz Podcast Dialogs — Сөздүн күчү"
task_categories:
- automatic-speech-recognition
- text-to-speech
- speaker-diarization
license: other
size_categories:
- n<1K
---

# Kyrgyz Podcast Dialogs — Сөздүн күчү

Разговорный кыргызский подкаст в той же **раскладке**, что [langswap/dialogs-ru-emotional-conversations](https://huggingface.co/datasets/langswap/dialogs-ru-emotional-conversations): `wavs/` + pipe-CSV + карточка.

Это **не** студийный эмоциональный корпус актёров. Это одно живое интервью (~36 мин), два спикера, целые реплики, тексты от ASR.

## Чем похоже на Dialogs

| | Dialogs (RU) | этот набор (KY) |
|---|---|---|
| Формат | `wavs/` + `metadata.csv` (`\|`) | то же |
| WAV | 44.1 kHz, 16-bit | 44.1 kHz, 16-bit, **mono** |
| Поля | путь, спикер, текст, длительность | то же + роль, язык, таймкоды |
| Стиль | 12 эмоций (актёры) | `conversational` (подкаст) |
| Объём | 20.6 ч, 11 796 реплик | **0.60 ч речи**, **31 реплика** |
| Текст | ручная расшифровка + ударения | **GigaAM-Multilingual large_ctc** |

## Состав

- Источник: [YouTube p3DNXhhp71w](https://youtu.be/p3DNXhhp71w), тема «Сөздүн күчү»
- Скачано как родной AAC 44.1 kHz, **без** перегона в MP3 и без шумоподавления
- Диаризация: NVIDIA NeMo `ClusteringDiarizer` (`vad_multilingual_marblenet` + `titanet_large`)
- ASR: `ai-sage/GigaAM-Multilingual`, revision `large_ctc`
- 2 спикера, 31 целая реплика (паузы одного человека до 3 с склеены)

| speaker_id | имя | роль | клипы | речь |
|---|---|---|---|---|
| `N` | Нуркыз Кадырбекова | guest | 15 | 1816 с |
| `G` | Гүлзада Таалайбекова | host | 16 | 355 с |

Всего: 2172 с речи, 4760 слов, 32 054 символа.

## Файлы

```
wavs/SPEAKER_00/*.wav
wavs/SPEAKER_01/*.wav
metadata.csv     # все строки, разделитель |
train.csv        # пока = весь корпус
podcast.json     # тот же набор, удобно для сайта/БД
README.md
```

Колонки CSV:

| field | описание |
|---|---|
| `audio_path` | путь к WAV (`wavs/...`) |
| `speaker_id` | `N` или `G` |
| `speaker_name` | имя |
| `role` | `guest` / `host` |
| `gender` | `F` |
| `language` | `ky` |
| `start_sec` / `end_sec` | таймкоды в исходном подкасте |
| `duration` | секунды |
| `text` | кыргызский текст (ASR) |
| `text_words` / `text_chars` | счётчики |
| `style` | `conversational` |
| `sample_rate` | 44100 |

Эмоций и ударений, как в Dialogs, **нет**: их не размечали. Поле `style` одно на все клипы.

## Как читать

```python
import pandas as pd
from pathlib import Path

root = Path("hf_ky_dialogs")
meta = pd.read_csv(root / "metadata.csv", sep="|")
wav = root / meta.audio_path.iloc[0]
print(meta.iloc[0][["speaker_name", "duration", "text"]])
print(wav)
```

## Ограничения

- Один выпуск, мало часов — для продакшен TTS/ASR нужно больше подкастов в том же формате.
- Реплики длинные (до ~4 мин). Dialogs режет ~6 с; для TTS лучше потом нарезать по фразам.
- Тексты автоматические (~10% WER на живом кыргызском у GigaAM Large). Для эталона нужна ручная правка.
- Имена спикеров взяты из расшифровки эфира, не из паспорта записи.

## Лицензия

Аудио принадлежит авторам ролика на YouTube. Этот пакет — рабочая разметка для своего сайта/БД, не выкладывать как открытый корпус без их согласия.

# Colab: второй подкаст (быстро, GPU)

Локальный CPU слишком долгий. Гони тот же процесс в Colab на **T4 GPU**.

Ноутбук: `colab_nemo.ipynb`  
Ролик: https://youtu.be/h1615IhITQ4  
2 спикера, NeMo + GigaAM, без MP3.

## Как открыть

1. https://colab.research.google.com
2. File → Upload notebook → `C:\Users\RedmiBook\Desktop\diarization\colab_nemo.ipynb`
   или с GitHub: https://colab.research.google.com/github/imdarriii/ky-podcast-dataset/blob/main/colab_nemo.ipynb
3. Runtime → Change runtime type → **T4 GPU** → Save
4. Runtime → Restart session
5. Runtime → **Run all**

Если YouTube в Colab заблокирует скачивание — ячейка 3 упадёт. Тогда скачай звук дома тем же yt-dlp (без `--audio-format mp3`) и залей файл в Files слева, ячейку 3 поправь на этот файл.

## Что скачать в конце

В Files появится `nemo_speakers_native.zip` (wav + podcast.json).  
Скачай и напиши мне — встрою реплики в публичный сайт.

Не используй `--extract-audio --audio-format mp3`.

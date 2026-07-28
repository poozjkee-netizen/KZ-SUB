#!/usr/bin/env python3
"""Прогнать ЛЮБУЮ модель Whisper по аудиофайлу и получить `.srt`.

Зачем: чтобы сравнивать модели честно, они должны проходить один и тот же
конвейер, что и прод — та же нарезка, оформление и постобработка. Скрипт
переиспользует модули `backend/app/`, поэтому отличие между прогонами ровно
одно: сама модель.

Запуск (из корня репозитория):
    python scripts/transcribe-local.py запись.wav --out текущий.srt
    python scripts/transcribe-local.py запись.wav --model ./kaz-rus-ct2 --out kazrus.srt

Затем сравнить:
    cd backend && python -m app.wer эталон.txt ../текущий.srt ../kazrus.srt

Модель задаётся именем (`large-v3`, `large-v3-turbo`) или путём к папке в
формате CTranslate2. На Mac считает на CPU — минутный ролик обрабатывается
за единицы минут, для замера этого достаточно.
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    p = argparse.ArgumentParser(description="Локальный прогон модели → .srt (NP SUB)")
    p.add_argument("audio", help="аудиофайл (.wav/.mp3/.m4a)")
    p.add_argument("--model", default=None,
                   help="имя модели или путь к папке CTranslate2 "
                        "(по умолчанию — как в конфиге, large-v3)")
    p.add_argument("--out", default=None, help="куда писать .srt (по умолчанию рядом с аудио)")
    p.add_argument("--device", default="cpu", help="cpu | cuda")
    p.add_argument("--compute-type", default="int8", help="int8 (cpu) | float16 (gpu)")
    p.add_argument("--initial-prompt", default=None,
                   help="затравка декодера (проверить эффект на код-свитчинг)")
    p.add_argument("--no-filters", action="store_true",
                   help="выключить VAD и пороги отсечения: проверить, не наши ли "
                        "фильтры съедают речь (диагностика пропущенных реплик)")
    args = p.parse_args()

    # Диагностика пропусков. Каждый фильтр умеет выбросить настоящую речь:
    # VAD не считает тихий участок речью, no_speech/log_prob отсекают реплику
    # по неуверенности модели, hallucination_silence_threshold пропускает
    # «тишину», compression_ratio выбрасывает повторяющийся текст. Прогон без
    # них показывает, где потолок модели, а где — наши настройки.
    if args.no_filters:
        os.environ["KZSUB_VAD_THRESHOLD"] = "0.2"
        os.environ["KZSUB_VAD_MIN_SILENCE_MS"] = "1000"
        os.environ["KZSUB_NO_SPEECH_THRESHOLD"] = "1.0"
        os.environ["KZSUB_LOG_PROB_THRESHOLD"] = "-10.0"
        os.environ["KZSUB_COMPRESSION_RATIO_THRESHOLD"] = "100.0"
        os.environ["KZSUB_HALLUCINATION_SILENCE_THRESHOLD"] = "0"
        os.environ["KZSUB_MAX_REPEATS"] = "0"

    # Переменные окружения выставляем ДО импорта app.config: он читает их
    # один раз при импорте модуля.
    if args.model:
        os.environ["KZSUB_WHISPER_MODEL"] = args.model
    os.environ["KZSUB_DEVICE"] = args.device
    os.environ["KZSUB_COMPUTE_TYPE"] = args.compute_type
    if args.initial_prompt is not None:
        os.environ["KZSUB_INITIAL_PROMPT"] = args.initial_prompt

    # Похоже на путь, но такой папки нет — говорим об этом прямо. Иначе
    # faster-whisper примет путь за имя репозитория на HuggingFace и ошибка
    # уведёт в сторону («Repo id must be in the form …»).
    if args.model and (os.sep in args.model or args.model.startswith("~")):
        model_dir = os.path.expanduser(args.model)
        if not os.path.isdir(model_dir):
            sys.exit(f"Нет папки с моделью: {model_dir}\n"
                     "Сконвертируй модель в формат CTranslate2 "
                     "(ct2-transformers-converter) — см. docs/ASR_PROVIDERS.md")
        os.environ["KZSUB_WHISPER_MODEL"] = model_dir

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "backend"))

    from app.config import settings
    from app.postprocess import postprocess
    from app.segmentation import resegment, resegment_words
    from app.srt import segments_to_srt
    from app.style import apply_style
    from app.transcribe import decode_options, transcribe_file

    print(f"Модель: {settings.whisper_model} ({settings.device}/{settings.compute_type})")
    opts = decode_options()
    print(f"Затравка: {opts.get('initial_prompt') or '—'}")
    if args.no_filters:
        print("Фильтры: выключены (VAD мягкий, пороги отсечения сняты)")
    print("Распознаю… (первый запуск скачивает веса)")

    raw_segments, duration = transcribe_file(args.audio)

    # Дальше — ровно тот же конвейер, что и в проде (main.py / runpod_handler.py).
    if settings.caption_style == "word":
        segments = resegment_words(raw_segments, glue_max_chars=settings.glue_max_chars)
    else:
        segments = resegment(
            raw_segments,
            max_line_chars=settings.max_line_chars,
            max_lines=settings.max_lines,
            max_cue_seconds=settings.max_cue_seconds,
            max_gap_seconds=settings.max_gap_seconds,
        )
    segments = apply_style(
        segments,
        uppercase=settings.uppercase,
        strip_punctuation=settings.strip_punctuation,
        punct_keep=settings.punct_keep,
    )
    segments = postprocess(segments)

    out_path = args.out or os.path.splitext(args.audio)[0] + ".srt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(segments_to_srt(segments))

    print(f"Готово: {out_path}  ({len(segments)} реплик, {duration:.0f} c аудио)")


if __name__ == "__main__":
    main()

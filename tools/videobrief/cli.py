"""NP Brief из командной строки — тот же прогон, что и в окне программы.

    python -m tools.videobrief "https://www.youtube.com/watch?v=..."

Окно: python -m tools.videobrief.webapp. Подробности — docs/VIDEO_BRIEF.md.
"""
from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):  # запуск файлом: python tools/videobrief/cli.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "videobrief"

from . import media, pipeline  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tools.videobrief",
        description="Ссылка на видео -> расшифровка -> разбор и сценарий на русском",
    )
    p.add_argument("source", help="ссылка на ролик или путь к локальному файлу")
    p.add_argument("--out", default="", help="куда складывать результат")
    p.add_argument("--audience", default="", help="под кого делаем свою версию")
    p.add_argument("--model", default="", help="файл модели .gguf для разбора")
    p.add_argument("--whisper", default="", help="модель распознавания речи")
    p.add_argument("--mode", choices=("auto", "subs", "asr"), default="auto",
                   help="откуда брать текст (по умолчанию — как получится)")
    p.add_argument("--transcript", default=None,
                   help="готовая расшифровка (.vtt/.srt/.txt) — пропустить скачивание")
    p.add_argument("--lang", default=None, help="язык речи (по умолчанию — авто)")
    p.add_argument("--no-analysis", action="store_true",
                   help="только расшифровка и готовый промпт, без разбора")
    p.add_argument("--quiet", action="store_true", help="без промежуточных сообщений")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    opts = pipeline.Options(
        source=args.source, out_root=args.out, audience=args.audience,
        model_path=args.model, whisper=args.whisper, mode=args.mode,
        transcript=args.transcript, lang=args.lang, analyze=not args.no_analysis,
    )

    def step(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    try:
        result = pipeline.run(opts, step)
    except (media.MediaError, RuntimeError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if result.analysis_error:
        print(f"Ошибка разбора: {result.analysis_error}", file=sys.stderr)
        print(f"Расшифровка сохранена: {result.out_dir}", file=sys.stderr)
        return 2

    step("Готово.")
    print(result.brief_path or result.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

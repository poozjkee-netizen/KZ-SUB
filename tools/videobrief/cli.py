"""VIDEO BRIEF — командная строка поверх общего конвейера (pipeline.py).

Запуск из корня репозитория:
    python -m tools.videobrief "https://www.youtube.com/watch?v=..."

То же самое умеет приложение для Mac (webapp.py) — оно зовёт тот же pipeline.run.
Что получится в папке out/briefs/<ролик>/ — см. docs/VIDEO_BRIEF.md.
"""
from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):  # запуск файлом: python tools/videobrief/cli.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "videobrief"

from . import media, pipeline  # noqa: E402
from .config import settings  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m tools.videobrief",
        description="Ссылка на видео -> транскрипция -> разбор и сценарий на русском",
    )
    p.add_argument("source", help="ссылка на ролик или путь к локальному файлу")
    p.add_argument("--out", default=settings.out_dir, help="куда складывать результат")
    p.add_argument("--audience", default=pipeline.AUDIENCE_DEFAULT,
                   help="под кого делаем свою версию (влияет на разбор)")
    p.add_argument("--mode", choices=("auto", "subs", "asr"), default="auto",
                   help="откуда брать текст: готовые субтитры, распознавание или "
                        "как получится (по умолчанию)")
    p.add_argument("--no-auto-subs", action="store_true",
                   help="не брать авто-субтитры площадки (они без пунктуации), "
                        "а распознавать звук")
    p.add_argument("--transcript", default=None,
                   help="готовая расшифровка (.vtt/.srt/.txt) — пропустить скачивание")
    p.add_argument("--lang", default=None,
                   help="язык речи для распознавания (по умолчанию — авто-детект)")
    p.add_argument("--model", default=settings.model, help="модель разбора")
    p.add_argument("--effort", default=settings.effort,
                   help="глубина разбора: low|medium|high|xhigh|max")
    p.add_argument("--max-tokens", type=int, default=settings.max_tokens,
                   help="потолок длины разбора")
    p.add_argument("--whisper", default=settings.whisper_model, help="модель Whisper")
    p.add_argument("--device", default=settings.device, help="cpu | cuda")
    p.add_argument("--compute-type", default=settings.compute_type,
                   help="int8 (cpu) | float16 (gpu)")
    p.add_argument("--no-analysis", action="store_true",
                   help="только расшифровка и готовый промпт, без обращения к модели")
    p.add_argument("--keep-audio", action="store_true",
                   help="не удалять скачанное аудио и субтитры (лежат в <out>/.work)")
    p.add_argument("--quiet", action="store_true", help="без промежуточных сообщений")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    opts = pipeline.Options(
        source=args.source, out_root=args.out, audience=args.audience,
        mode=args.mode, auto_subs=not args.no_auto_subs, transcript=args.transcript,
        lang=args.lang, model=args.model, effort=args.effort,
        max_tokens=args.max_tokens, whisper=args.whisper, device=args.device,
        compute_type=args.compute_type, analyze=not args.no_analysis,
        keep_work=args.keep_audio,
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
        print(f"Расшифровка и промпт всё равно сохранены: {result.out_dir}",
              file=sys.stderr)
        return 2

    step("Готово.")
    print(result.brief_path or result.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

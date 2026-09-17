"""VIDEO BRIEF — командная строка: ссылка на ролик -> разбор и сценарий.

Запуск из корня репозитория:
    python -m tools.videobrief "https://www.youtube.com/watch?v=..."

Что получится в папке out/briefs/<имя-ролика>/:
    brief.md            — разбор: о чём ролик, структура, каркас, свой черновик
    transcript.txt      — чистый текст ролика (как сказано, без тайм-кодов)
    transcript.timed.txt— тот же текст с тайм-кодами
    prompt.txt          — задание, которое ушло модели (можно доработать руками)
    meta.json           — метаданные ролика и как он был расшифрован
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

if __package__ in (None, ""):  # запуск файлом: python tools/videobrief/cli.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "videobrief"

from . import asr, captions, media, prompt as prompt_mod, report, transcript as tr  # noqa: E402
from .config import settings  # noqa: E402

AUDIENCE_DEFAULT = "русскоязычная аудитория СНГ"


def _log(quiet: bool, message: str) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m tools.videobrief",
        description="Ссылка на видео -> транскрипция -> разбор и сценарий на русском",
    )
    p.add_argument("source", help="ссылка на ролик или путь к локальному файлу")
    p.add_argument("--out", default=settings.out_dir, help="куда складывать результат")
    p.add_argument("--audience", default=AUDIENCE_DEFAULT,
                   help="под кого делаем свою версию (влияет на разбор)")
    p.add_argument("--mode", choices=("auto", "subs", "asr"), default="auto",
                   help="откуда брать текст: готовые субтитры, распознавание или "
                        "как получится (по умолчанию)")
    p.add_argument("--auto-subs", action="store_true",
                   help="разрешить авто-субтитры площадки (быстро, но без пунктуации)")
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


def _fill(meta: dict, key: str, value) -> None:
    """Проставляет поле, если его нет ИЛИ оно пустое.

    setdefault тут не годится: yt-dlp кладёт пустые строки вместо отсутствующих
    полей, и они молча побеждали бы наши запасные значения.
    """
    if not meta.get(key):
        meta[key] = value


def _read_transcript_file(path: str) -> list[tr.Segment]:
    """Готовая расшифровка с диска: .vtt/.srt — с тайм-кодами, .txt — сплошняком."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    for parse in (captions.parse, tr.parse_timed_text):
        segments = parse(content)
        if segments:
            return segments
    text = " ".join(content.split())
    return [tr.Segment(start=0.0, end=0.0, text=text)] if text else []


def _collect(args: argparse.Namespace, workdir: str,
             quiet: bool) -> tuple[list[tr.Segment], dict, str, bool]:
    """Достаёт расшифровку и метаданные. -> (сегменты, мета, чем расшифровано, авто?)."""
    is_local = os.path.exists(args.source)

    if args.transcript:
        meta = ({} if is_local or not args.source.startswith("http")
                else media.meta_from_info(media.probe(args.source)))
        _fill(meta, "title", os.path.splitext(os.path.basename(args.source))[0])
        _fill(meta, "url", args.source)
        _log(quiet, f"Беру готовую расшифровку: {args.transcript}")
        return _read_transcript_file(args.transcript), meta, "файл на диске", False

    if is_local:
        meta = {"title": os.path.splitext(os.path.basename(args.source))[0],
                "url": os.path.abspath(args.source)}
        audio_path = args.source
    else:
        _log(quiet, "Читаю метаданные ролика…")
        info = media.probe(args.source)
        meta = media.meta_from_info(info)
        if args.mode != "asr":
            track = media.pick_subtitle_track(
                info, [s.strip() for s in settings.sub_langs.split(",") if s.strip()],
                allow_auto=args.auto_subs,
            )
            if track:
                lang, is_auto = track
                kind = "авто-субтитры" if is_auto else "субтитры автора"
                _log(quiet, f"Беру {kind} ({lang})…")
                segments = captions.parse(
                    media.fetch_subtitles(args.source, lang, is_auto, workdir))
                if segments:
                    _fill(meta, "language", lang.split("-")[0])
                    return segments, meta, f"{kind} ролика, язык {lang}", is_auto
                _log(quiet, "Субтитры пустые — распознаю звук.")
            elif args.mode == "subs":
                raise media.MediaError(
                    "У ролика нет готовых субтитров. Запусти без --mode subs "
                    "(распознаем звук) или добавь --auto-subs."
                )
            else:
                _log(quiet, "Готовых субтитров нет — распознаю звук.")
        if args.mode == "subs":
            raise media.MediaError(
                "Субтитры не дали текста, а --mode subs запрещает распознавание.")
        _log(quiet, "Скачиваю аудио…")
        audio_path = media.fetch_audio(args.source, workdir)

    _log(quiet, f"Распознаю речь ({args.whisper}, {args.device}) — это дольше всего…")
    segments, detected = asr.transcribe(
        audio_path, args.whisper, args.device, args.compute_type, args.lang)
    if detected:
        _fill(meta, "language", detected)
    return segments, meta, f"Whisper {args.whisper}, язык {detected or 'не определён'}", False


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    quiet = args.quiet

    workdir_parent = os.path.abspath(args.out)
    os.makedirs(workdir_parent, exist_ok=True)
    workdir = os.path.join(workdir_parent, ".work")
    os.makedirs(workdir, exist_ok=True)

    try:
        segments, meta, source_note, is_auto = _collect(args, workdir, quiet)
    except (media.MediaError, RuntimeError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if not segments:
        print("Ошибка: в ролике не нашлось речи — разбирать нечего.", file=sys.stderr)
        return 1

    if is_auto:
        # Авто-субтитры идут «бегущей строкой» с повторами — без чистки текст
        # раздувается вдвое и сбивает разбор.
        segments = tr.dedupe_rolling(segments)
    blocks = tr.merge_blocks(segments)
    _fill(meta, "duration", tr.duration(segments))

    out_dir = os.path.join(workdir_parent, report.folder_name(meta))
    os.makedirs(out_dir, exist_ok=True)

    clean = tr.clean_text(blocks)
    timed = tr.timed_text(blocks)
    task = prompt_mod.build(meta, timed, args.audience, source_note)

    _write(os.path.join(out_dir, "transcript.txt"), clean)
    _write(os.path.join(out_dir, "transcript.timed.txt"), timed)
    _write(os.path.join(out_dir, "prompt.txt"), task + "\n")
    _write(os.path.join(out_dir, "meta.json"),
           json.dumps({**meta, "transcript_source": source_note},
                      ensure_ascii=False, indent=2) + "\n")

    if not args.keep_audio:
        shutil.rmtree(workdir, ignore_errors=True)

    if args.no_analysis:
        _log(quiet, "Разбор пропущен (--no-analysis).")
        print(out_dir)
        return 0

    from .analyze import AnalyzeError, analyze  # импорт тут: без ключа тоже работаем

    _log(quiet, f"Разбираю ролик ({args.model})…")
    try:
        analysis = analyze(prompt_mod.SYSTEM, task, args.model, args.effort,
                           args.max_tokens, progress=not quiet)
    except AnalyzeError as exc:
        print(f"Ошибка разбора: {exc}", file=sys.stderr)
        print(f"Расшифровка и промпт всё равно сохранены: {out_dir}", file=sys.stderr)
        return 2

    brief_path = os.path.join(out_dir, "brief.md")
    _write(brief_path, report.header(meta, source_note, args.model) + analysis + "\n")
    _log(quiet, "Готово.")
    print(brief_path)
    return 0


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    raise SystemExit(main())

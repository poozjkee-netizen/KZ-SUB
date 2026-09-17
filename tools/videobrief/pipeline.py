"""Весь прогон целиком: ссылка -> файлы на диске.

Отдельно от cli.py, потому что у прогона два лица: командная строка и окно
приложения (webapp.py). Разводить их по копиям кода нельзя — разойдутся.
Поэтому здесь нет ни print, ни argparse: о ходе дела сообщает колбэк `on_step`.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable

from . import asr, captions, media, prompt as prompt_mod, report, transcript as tr
from .config import settings

AUDIENCE_DEFAULT = "русскоязычная аудитория СНГ"


@dataclass
class Options:
    """Что и как разбираем. Значения по умолчанию — как в командной строке."""
    source: str                       # ссылка или путь к файлу
    out_root: str = settings.out_dir
    audience: str = AUDIENCE_DEFAULT
    mode: str = "auto"                # auto | subs | asr
    auto_subs: bool = True
    transcript: str | None = None
    lang: str | None = None
    model: str = settings.model
    effort: str = settings.effort
    max_tokens: int = settings.max_tokens
    whisper: str = settings.whisper_model
    device: str = settings.device
    compute_type: str = settings.compute_type
    analyze: bool = True
    keep_work: bool = False
    api_key: str | None = None        # ключ из настроек приложения


@dataclass
class Result:
    """Итог прогона: куда что легло и чем расшифровано."""
    out_dir: str
    transcript_path: str
    timed_path: str
    prompt_path: str
    meta_path: str
    meta: dict
    source_note: str
    brief_path: str | None = None
    analysis_error: str | None = None
    files: dict = field(default_factory=dict)


Step = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def _fill(meta: dict, key: str, value) -> None:
    """Проставляет поле, если его нет ИЛИ оно пустое.

    setdefault тут не годится: yt-dlp кладёт пустые строки вместо отсутствующих
    полей, и они молча побеждали бы наши запасные значения.
    """
    if not meta.get(key):
        meta[key] = value


def read_transcript_file(path: str) -> list[tr.Segment]:
    """Готовая расшифровка с диска: .vtt/.srt/наш '[MM:SS] …' или сплошной текст."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    for parse in (captions.parse, tr.parse_timed_text):
        segments = parse(content)
        if segments:
            return segments
    text = " ".join(content.split())
    return [tr.Segment(start=0.0, end=0.0, text=text)] if text else []


def collect(opts: Options, workdir: str,
            on_step: Step = _noop) -> tuple[list[tr.Segment], dict, str, bool]:
    """Достаёт расшифровку и метаданные. -> (сегменты, мета, чем расшифровано, авто?)."""
    is_local = os.path.exists(opts.source)

    if opts.transcript:
        meta = ({} if is_local or not opts.source.startswith("http")
                else media.meta_from_info(media.probe(opts.source)))
        _fill(meta, "title", os.path.splitext(os.path.basename(opts.source))[0])
        _fill(meta, "url", opts.source)
        on_step(f"Беру готовую расшифровку: {os.path.basename(opts.transcript)}")
        return read_transcript_file(opts.transcript), meta, "файл на диске", False

    if is_local:
        meta = {"title": os.path.splitext(os.path.basename(opts.source))[0],
                "url": os.path.abspath(opts.source)}
        audio_path = opts.source
    else:
        on_step("Читаю ролик по ссылке…")
        info = media.probe(opts.source)
        meta = media.meta_from_info(info)
        if meta.get("title"):
            on_step(f"Ролик: {meta['title']}")
        if opts.mode != "asr":
            track = media.pick_subtitle_track(
                info, [s.strip() for s in settings.sub_langs.split(",") if s.strip()],
                allow_auto=opts.auto_subs,
            )
            if track:
                lang, is_auto = track
                kind = "авто-субтитры" if is_auto else "субтитры автора"
                on_step(f"Беру {kind} ({lang}) — это быстро")
                segments = captions.parse(
                    media.fetch_subtitles(opts.source, lang, is_auto, workdir))
                if segments:
                    _fill(meta, "language", lang.split("-")[0])
                    return segments, meta, f"{kind} ролика, язык {lang}", is_auto
                on_step("Субтитры пустые — распознаю звук")
            elif opts.mode == "subs":
                raise media.MediaError(
                    "У ролика нет готовых субтитров, а режим «только субтитры» "
                    "запрещает распознавание."
                )
            else:
                on_step("Готовых субтитров нет — распознаю звук")
        if opts.mode == "subs":
            raise media.MediaError(
                "Субтитры не дали текста, а режим «только субтитры» запрещает "
                "распознавание.")
        on_step("Скачиваю аудиодорожку…")
        audio_path = media.fetch_audio(opts.source, workdir)

    on_step(f"Распознаю речь ({opts.whisper}) — это самая долгая часть")
    segments, detected = asr.transcribe(
        audio_path, opts.whisper, opts.device, opts.compute_type, opts.lang)
    if detected:
        _fill(meta, "language", detected)
    return segments, meta, f"Whisper {opts.whisper}, язык {detected or 'не определён'}", False


def run(opts: Options, on_step: Step = _noop) -> Result:
    """Полный прогон. Бросает MediaError/RuntimeError, если материал не достался.

    Ошибка разбора моделью прогон НЕ валит: расшифровка уже получена и стоила
    времени, поэтому она сохраняется, а причина кладётся в `analysis_error`.
    """
    out_root = os.path.abspath(opts.out_root)
    workdir = os.path.join(out_root, ".work")
    os.makedirs(workdir, exist_ok=True)

    segments, meta, source_note, is_auto = collect(opts, workdir, on_step)
    if not segments:
        raise media.MediaError("В ролике не нашлось речи — разбирать нечего.")

    if is_auto:
        # Авто-субтитры идут «бегущей строкой» с повторами — без чистки текст
        # раздувается вдвое и сбивает разбор.
        segments = tr.dedupe_rolling(segments)
    blocks = tr.merge_blocks(segments)
    _fill(meta, "duration", tr.duration(segments))

    out_dir = os.path.join(out_root, report.folder_name(meta))
    os.makedirs(out_dir, exist_ok=True)

    clean = tr.clean_text(blocks)
    timed = tr.timed_text(blocks)
    task = prompt_mod.build(meta, timed, opts.audience, source_note)

    paths = {
        "transcript": os.path.join(out_dir, "transcript.txt"),
        "timed": os.path.join(out_dir, "transcript.timed.txt"),
        "prompt": os.path.join(out_dir, "prompt.txt"),
        "meta": os.path.join(out_dir, "meta.json"),
    }
    write(paths["transcript"], clean)
    write(paths["timed"], timed)
    write(paths["prompt"], task + "\n")
    write(paths["meta"], json.dumps({**meta, "transcript_source": source_note},
                                    ensure_ascii=False, indent=2) + "\n")

    if not opts.keep_work:
        shutil.rmtree(workdir, ignore_errors=True)

    result = Result(out_dir=out_dir, transcript_path=paths["transcript"],
                    timed_path=paths["timed"], prompt_path=paths["prompt"],
                    meta_path=paths["meta"], meta=meta, source_note=source_note,
                    files={"clean": clean, "timed": timed})
    if not opts.analyze:
        return result

    from .analyze import AnalyzeError, analyze  # импорт тут: без ключа тоже работаем

    on_step("Разбираю ролик — это пара минут")
    try:
        analysis = analyze(prompt_mod.SYSTEM, task, opts.model, opts.effort,
                           opts.max_tokens, progress=False, api_key=opts.api_key)
    except AnalyzeError as exc:
        result.analysis_error = str(exc)
        return result

    result.brief_path = os.path.join(out_dir, "brief.md")
    brief = report.header(meta, source_note, opts.model) + analysis + "\n"
    write(result.brief_path, brief)
    result.files["brief"] = brief
    return result


def write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

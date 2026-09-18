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

from . import (asr, captions, local_llm, longtext, media, prompt as prompt_mod,
               report, transcript as tr)
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
    engine: str = settings.engine     # auto | local | claude
    local_url: str = settings.local_url
    local_model: str = settings.local_model
    local_ctx: int = settings.local_ctx
    local_max_chars: int = settings.local_max_chars


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
    engine_note: str = ""             # чем разобрано: модель и где она крутится
    files: dict = field(default_factory=dict)


Step = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def _short(exc: Exception, limit: int = 60) -> str:
    """Короткая причина отказа для строки статуса — без простыни из stderr."""
    text = " ".join(str(exc).split())
    if "429" in text:
        return "площадка ограничила запросы"
    return text[:limit] + ("…" if len(text) > limit else "")


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
                # Площадка может не отдать субтитры (429 «слишком много
                # запросов», приватный ролик, сломанная дорожка). Это не повод
                # ронять прогон: звук у нас уже есть откуда взять.
                try:
                    segments = captions.parse(
                        media.fetch_subtitles(opts.source, lang, is_auto, workdir))
                except media.MediaError as exc:
                    if opts.mode == "subs":
                        raise
                    on_step(f"Субтитры не отдались ({_short(exc)}) — распознаю звук")
                else:
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

    try:
        analysis, engine_note = analyze_text(opts, meta, timed, source_note, on_step)
    except (local_llm.LocalLLMError, RuntimeError) as exc:
        result.analysis_error = str(exc)
        return result

    result.engine_note = engine_note
    result.brief_path = os.path.join(out_dir, "brief.md")
    brief = report.header(meta, source_note, engine_note) + analysis + "\n"
    write(result.brief_path, brief)
    result.files["brief"] = brief
    return result


def choose_engine(opts: Options) -> tuple[str, local_llm.Server | None]:
    """Кем разбирать: локальной моделью или Claude. -> (движок, сервер или None).

    "auto" сначала стучится в локальную модель: если она запущена, разбор идёт
    на устройстве — без интернета, ключей и оплаты. Нет локальной — берём Claude,
    но только если есть ключ, иначе честно говорим, чего не хватает.
    """
    if opts.engine == "claude":
        return "claude", None
    try:
        server = local_llm.detect(opts.local_url)
        return "local", server
    except local_llm.LocalLLMError:
        if opts.engine == "local":
            raise
        if not (opts.api_key or os.environ.get("ANTHROPIC_API_KEY")):
            raise local_llm.LocalLLMError(
                "Разбирать нечем: локальная модель не запущена, ключ Anthropic не задан. "
                "Запусти Ollama (ollama serve) или добавь ключ в настройках. "
                "Расшифровка при этом уже сохранена."
            )
        return "claude", None


def analyze_local(opts: Options, server: local_llm.Server, meta: dict, timed: str,
                  source_note: str, on_step: Step) -> tuple[str, str]:
    """Разбор локальной моделью. Длинную расшифровку сначала сжимает по частям."""
    model = local_llm.pick_model(server.models, opts.local_model)
    if not model:
        raise local_llm.LocalLLMError(
            "На локальном сервере нет ни одной модели. Загрузи её "
            "(например: ollama pull gemma3:12b) и повтори."
        )

    note = source_note
    if longtext.needs_condensing(timed, opts.local_max_chars):
        parts = longtext.split_lines(timed, opts.local_max_chars)
        notes: list[str] = []
        for index, part in enumerate(parts, 1):
            on_step(f"Ролик длинный: сжимаю часть {index} из {len(parts)} ({model})")
            notes.append(local_llm.chat(
                server, model, prompt_mod.CONDENSE_SYSTEM,
                prompt_mod.build_condense(part, index, len(parts)),
                num_ctx=opts.local_ctx))
        timed = "\n\n".join(notes)
        note = f"{source_note}; длинный ролик сжат по частям"

    task = prompt_mod.build(meta, timed, opts.audience, note)
    on_step(f"Разбираю на устройстве: {model}")
    text = local_llm.chat(server, model, prompt_mod.SYSTEM, task, num_ctx=opts.local_ctx)
    return text, f"{model} (локально, {server.kind})"


def analyze_text(opts: Options, meta: dict, timed: str, source_note: str,
                 on_step: Step) -> tuple[str, str]:
    """Отдаёт разбор и подпись «чем разобрано». Ошибки — понятным языком."""
    engine, server = choose_engine(opts)
    if engine == "local" and server is not None:
        return analyze_local(opts, server, meta, timed, source_note, on_step)

    from .analyze import AnalyzeError, analyze  # импорт тут: без ключа тоже работаем

    on_step(f"Разбираю в облаке: {opts.model}")
    try:
        task = prompt_mod.build(meta, timed, opts.audience, source_note)
        text = analyze(prompt_mod.SYSTEM, task, opts.model, opts.effort,
                       opts.max_tokens, progress=False, api_key=opts.api_key)
    except AnalyzeError as exc:
        raise RuntimeError(str(exc)) from exc
    return text, opts.model


def write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

"""Разбор расшифровки моделью Claude.

Запрос всегда стриминговый: разбор длинный (структура + сценарий + черновик
своей версии), а нестриминговый вызов с таким max_tokens упирается в таймаут
HTTP и падает уже после того, как деньги потрачены.
"""
from __future__ import annotations

import sys


class AnalyzeError(RuntimeError):
    """Модель недоступна или отказалась отвечать."""


def analyze(system: str, user: str, model: str, effort: str, max_tokens: int,
            progress: bool = True) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise AnalyzeError(
            "Не установлен пакет anthropic: pip install anthropic\n"
            "Либо запусти с --no-analysis — тогда получишь расшифровку и готовый "
            "промпт, который можно вставить в чат вручную."
        ) from exc

    client = anthropic.Anthropic()
    chunks: list[str] = []
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                chunks.append(text)
                if progress:
                    # Признак жизни: разбор идёт минуты, молчащий терминал
                    # выглядит как зависший.
                    sys.stderr.write(".")
                    sys.stderr.flush()
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise AnalyzeError(
            "Ключ Anthropic не принят. Задай ANTHROPIC_API_KEY или выполни ant auth login."
        ) from exc
    except anthropic.APIStatusError as exc:
        raise AnalyzeError(f"Ошибка API ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AnalyzeError("Нет связи с API Anthropic — проверь сеть.") from exc
    finally:
        if progress:
            sys.stderr.write("\n")

    if message.stop_reason == "refusal":
        raise AnalyzeError("Модель отказалась разбирать этот ролик.")
    text = "".join(chunks).strip()
    if message.stop_reason == "max_tokens":
        text += ("\n\n> Разбор оборван на лимите длины. Увеличь VIDEOBRIEF_MAX_TOKENS "
                 "и запусти ещё раз с --transcript на уже готовой расшифровке.")
    if not text:
        raise AnalyzeError("Модель вернула пустой ответ.")
    return text

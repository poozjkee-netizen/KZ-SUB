"""Локальная модель прямо в процессе программы: файл .gguf, без сервера.

Почему без сервера: сервер — это лишний запущенный процесс, порт, окно
терминала и ещё одна вещь, которая «не отвечает». llama-cpp-python грузит
.gguf сам и считает на видеокарте мака (Metal), а модель остаётся в памяти
между роликами — второй разбор начинается сразу.

Единственная тяжёлая зависимость программы кроме распознавания речи.
"""
from __future__ import annotations

import os
from typing import Callable

# Где обычно лежат .gguf на маке: своя папка, Cotypist, LM Studio, загрузки.
MODEL_DIRS = (
    "~/Models",
    "~/Library/Application Support/NPAutocomplete/Models",
    "~/.cache/lm-studio/models",
    "~/.lmstudio/models",
    "~/Downloads",
)

# Файлы меньше этого — словари и обрывки, а не модели.
MIN_MODEL_BYTES = 100 * 1024 * 1024

_loaded: dict[tuple[str, int], object] = {}


class LLMError(RuntimeError):
    """Модель не найдена, не загрузилась или ответила пустым."""


def is_instruct(name: str) -> bool:
    """Инструкт-версия? Базовая модель указаний не выполняет — она продолжает текст."""
    low = os.path.basename(name).lower()
    return any(mark in low for mark in ("-it", "instruct", "-chat", "it-"))


def find_models(dirs: tuple[str, ...] | None = None) -> list[str]:
    """Все .gguf в обычных местах: сначала инструкт-версии, внутри — крупные.

    Список папок берётся в момент вызова, а не при загрузке модуля: иначе
    подмена MODEL_DIRS (тесты, своя папка) не действовала бы.
    """
    found: list[tuple[bool, int, str]] = []
    for raw in (dirs or MODEL_DIRS):
        base = os.path.expanduser(raw)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for name in files:
                if not name.endswith(".gguf"):
                    continue
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if size >= MIN_MODEL_BYTES:
                    found.append((is_instruct(name), size, path))
    # Крупнее — обычно сильнее; инструкт-версии всегда выше базовых.
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [path for _it, _size, path in found]


def pick(models: list[str], preferred: str = "") -> str:
    """Какую модель взять: заданную, иначе лучшую из найденных."""
    if preferred and os.path.isfile(os.path.expanduser(preferred)):
        return os.path.expanduser(preferred)
    if preferred:
        low = preferred.lower()
        for path in models:
            if low in os.path.basename(path).lower():
                return path
    return models[0] if models else ""


def load(model_path: str, ctx: int):
    """Загружает модель и держит её в памяти до конца работы программы."""
    key = (model_path, ctx)
    if key in _loaded:
        return _loaded[key]
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise LLMError(
            "Не установлен llama-cpp-python — это он читает файлы .gguf.\n"
            "Поставь его: pip install llama-cpp-python"
        ) from exc
    try:
        model = Llama(
            model_path=model_path,
            n_ctx=ctx,
            n_gpu_layers=-1,   # всё на видеокарту: на маке это Metal
            verbose=False,
        )
    except Exception as exc:  # модель может быть битой или не влезть в память
        raise LLMError(f"Модель не загрузилась: {exc}") from exc
    _loaded[key] = model
    return model


def generate(model_path: str, system: str, user: str, ctx: int = 16384,
             max_tokens: int = 4096,
             on_token: Callable[[str], None] | None = None) -> str:
    """Один запрос к модели. Ответ собирается потоком — видно, что она жива."""
    model = load(model_path, ctx)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    chunks: list[str] = []
    try:
        stream = model.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=0.4, stream=True)
        for piece in stream:
            delta = (piece.get("choices") or [{}])[0].get("delta") or {}
            text = delta.get("content") or ""
            if text:
                chunks.append(text)
                if on_token:
                    on_token(text)
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"Модель оборвала ответ: {exc}") from exc

    answer = "".join(chunks).strip()
    if not answer:
        raise LLMError("Модель вернула пустой ответ.")
    return answer

"""Разбор локальной моделью (Gemma и любая другая) — без интернета и без ключей.

Поддержаны два способа, которыми локальные модели отдаются наружу, и этого
хватает почти на всё, что стоит на маке:
  • Ollama — свой протокол, порт 11434;
  • OpenAI-совместимый /v1 — LM Studio (1234), llama.cpp server / llama-server
    (8080), text-generation-webui и прочие.

Сервер и модель определяются сами: спрашиваем список моделей и берём Gemma,
если она есть. Только stdlib — ни одной зависимости ради локального разбора.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# Куда стучимся, если адрес не задан. Порядок = вероятность встретить на маке.
DEFAULT_ENDPOINTS = (
    "http://127.0.0.1:11434",  # Ollama
    "http://127.0.0.1:1234",   # LM Studio
    "http://127.0.0.1:8080",   # llama.cpp server
)


class LocalLLMError(RuntimeError):
    """Локальная модель недоступна или ответила негодным."""


@dataclass
class Server:
    base: str
    kind: str                      # "ollama" | "openai"
    models: list[str] = field(default_factory=list)


def _get_json(url: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_model(models: list[str], preferred: str = "") -> str:
    """Какую модель взять из списка. Чистая функция — закрыта тестом.

    Точное совпадение с выбранной > gemma > instruct/chat > первая в списке.
    Gemma в приоритете не случайно: она вменяемо держит длинные инструкции на
    русском, а разбор — это ровно длинная инструкция.
    """
    if not models:
        return ""
    if preferred:
        for name in models:
            if name == preferred:
                return name
        for name in models:  # «gemma3» должно находить «gemma3:12b»
            if preferred.lower() in name.lower():
                return name
    for needle in ("gemma", "instruct", "chat"):
        for name in models:
            if needle in name.lower():
                return name
    return models[0]


def probe(base: str, timeout: float = 3.0) -> Server | None:
    """Проверяет один адрес: что там за сервер и какие модели. None — пусто."""
    base = base.rstrip("/")
    try:
        data = _get_json(f"{base}/api/tags", timeout)
        names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        if names or "models" in data:
            return Server(base=base, kind="ollama", models=names)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        pass
    try:
        data = _get_json(f"{base}/v1/models", timeout)
        names = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        if names or "data" in data:
            return Server(base=base, kind="openai", models=names)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        pass
    return None


def detect(base: str = "", timeout: float = 3.0) -> Server:
    """Находит локальный сервер: по заданному адресу или перебором обычных портов."""
    candidates = [base] if base else list(DEFAULT_ENDPOINTS)
    for candidate in candidates:
        server = probe(candidate, timeout)
        if server:
            return server
    raise LocalLLMError(
        "Локальная модель не отвечает. Запусти её и повтори:\n"
        "  • Ollama:    ollama serve   (модели: ollama list)\n"
        "  • LM Studio: включи Local Server во вкладке Developer\n"
        "  • llama.cpp: llama-server -m модель.gguf --port 8080\n"
        "Либо укажи адрес сервера в настройках."
    )


def _request(url: str, payload: dict, timeout: float):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def chat(server: Server, model: str, system: str, user: str,
         num_ctx: int = 16384, temperature: float = 0.4,
         timeout: float = 900.0,
         on_token: Callable[[str], None] | None = None) -> str:
    """Один запрос к локальной модели. Возвращает текст ответа целиком.

    Ответ читается потоком: разбор идёт минутами, и без потока соединение
    молчит так долго, что рвётся по таймауту. Заодно видно, что модель жива.
    """
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    if server.kind == "ollama":
        url = f"{server.base}/api/chat"
        payload = {"model": model, "messages": messages, "stream": True,
                   # num_ctx у Ollama по умолчанию мал — длинная расшифровка
                   # молча обрежется, и модель разберёт половину ролика.
                   "options": {"temperature": temperature, "num_ctx": num_ctx}}
    else:
        url = f"{server.base}/v1/chat/completions"
        payload = {"model": model, "messages": messages, "stream": True,
                   "temperature": temperature}

    chunks: list[str] = []
    try:
        with _request(url, payload, timeout) as resp:
            for raw in resp:
                piece = _parse_chunk(raw.decode("utf-8", "replace"), server.kind)
                if piece:
                    chunks.append(piece)
                    if on_token:
                        on_token(piece)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise LocalLLMError(f"Модель ответила ошибкой {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise LocalLLMError(f"Связь с локальной моделью оборвалась: {exc}") from exc

    text = "".join(chunks).strip()
    if not text:
        raise LocalLLMError("Локальная модель вернула пустой ответ.")
    return text


def _parse_chunk(line: str, kind: str) -> str:
    """Одна строка потока -> кусок текста. Разные протоколы, один вход."""
    line = line.strip()
    if not line:
        return ""
    if kind == "openai":
        if not line.startswith("data:"):
            return ""
        line = line[5:].strip()
        if line == "[DONE]":
            return ""
    try:
        data = json.loads(line)
    except ValueError:
        return ""
    if kind == "ollama":
        return (data.get("message") or {}).get("content") or ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or choices[0].get("message") or {}
    return delta.get("content") or ""

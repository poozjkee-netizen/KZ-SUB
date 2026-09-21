"""Окно NP Brief: вставил ссылку, нажал кнопку, получил разбор.

Устроено как крошечный локальный сервер на stdlib, окно которого открывается в
браузере. Нативное окно на Python тянет PyObjC/Tk — они ломаются от версии к
версии macOS; здесь ноль зависимостей сверх самой программы, а для человека это
всё равно двойной клик по NP Brief.app.

Слушает только 127.0.0.1 и требует токен из адреса: без него чужая страница в
браузере могла бы запустить прогон и прочитать настройки.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):  # запуск файлом: python webapp.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "videobrief"

from . import llm, media, pipeline, settings  # noqa: E402

UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")
TOKEN = secrets.token_urlsafe(16)

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_current: str | None = None


def _run_job(job: dict) -> None:
    """Прогон в фоне. Шаги копятся в job['steps'] — окно их опрашивает."""
    global _current
    started = time.monotonic()

    def tick(message: str) -> None:
        """Обновляет последнюю строку статуса, пока модель пишет ответ."""
        if job["steps"]:
            job["steps"][-1] = message

    try:
        result = pipeline.run(pipeline.Options(source=job["url"]),
                              job["steps"].append, tick)
    except (media.MediaError, RuntimeError, OSError) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
    else:
        job["status"] = "done"
        job["result"] = {
            "out_dir": result.out_dir,
            "title": result.meta.get("title") or "",
            "brief": result.files.get("brief", ""),
            # Текст ролика по-русски — то, что человек читает по умолчанию.
            "script_ru": result.files.get("script_ru", ""),
            "original": result.files.get("timed", ""),
            "analysis_error": result.analysis_error,
            "model_note": result.model_note,
            # Сколько заняло — единственная цифра, которую человек не знает сам.
            "elapsed": int(time.monotonic() - started),
        }
    finally:
        with _lock:
            _current = None


class Handler(BaseHTTPRequestHandler):
    server_version = "NPBrief"

    def log_message(self, *args) -> None:  # тише в консоли: это не веб-сервер
        pass

    def _authorized(self, query: dict) -> bool:
        return secrets.compare_digest((query.get("t") or [""])[0], TOKEN)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return

        if parsed.path == "/":
            with open(UI_PATH, "rb") as fh:
                page = fh.read().replace(b"__TOKEN__", TOKEN.encode())
            self._send(200, page, "text/html; charset=utf-8")
        elif parsed.path == "/api/state":
            job_id = (query.get("job") or [""])[0]
            self._json({"settings": settings.load(), "job": _jobs.get(job_id)})
        elif parsed.path == "/api/models":
            # Что лежит на диске: показываем список, чтобы не заставлять
            # человека искать путь к файлу руками.
            models = llm.find_models()
            self._json({"models": [{"path": p, "name": os.path.basename(p)}
                                   for p in models[:20]],
                        "dirs": [os.path.expanduser(d) for d in llm.MODEL_DIRS]})
        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        global _current
        parsed = urlparse(self.path)
        if not self._authorized(parse_qs(parsed.query)):
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        body = self._body()

        if parsed.path == "/api/run":
            url = (body.get("url") or "").strip()
            if not url:
                self._json({"error": "Вставь ссылку на ролик."}, 400)
                return
            with _lock:
                if _current is not None:
                    self._json({"error": "Уже разбираю один ролик — дождись конца."}, 409)
                    return
                job = {"id": uuid.uuid4().hex[:12], "url": url, "status": "running",
                       "steps": ["Начинаю…"], "error": None, "result": None}
                _jobs[job["id"]] = job
                _current = job["id"]
            threading.Thread(target=_run_job, args=(job,), daemon=True).start()
            self._json({"job": job["id"]})

        elif parsed.path == "/api/settings":
            self._json({"settings": settings.save(body)})

        elif parsed.path == "/api/reveal":
            path = (body.get("path") or "").strip()
            if path and os.path.exists(path):
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, path])
                self._json({"ok": True})
            else:
                self._json({"error": "Папка не найдена."}, 404)

        elif parsed.path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")


def serve(port: int = 0, open_browser: bool = True) -> None:
    """Поднимает окно программы. port=0 — свободный порт выберет система."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={TOKEN}"
    print(f"NP Brief: {url}", flush=True)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve(port=int(os.environ.get("VIDEOBRIEF_PORT", "0")))

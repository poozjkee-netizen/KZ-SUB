"""NP Brief — окно приложения: вставил ссылку, нажал кнопку, получил разбор.

Устроено как крошечный локальный сервер на stdlib, окно которого открывается в
браузере. Почему так, а не «настоящее» окно: нативный GUI на Python тянет
зависимости (PyObjC/Tk), которые ломаются от версии к версии macOS, а тут ноль
зависимостей сверх самого инструмента, и интерфейс одинаково работает на любом
маке. Для человека разницы нет: он двойным кликом открывает NP Brief.app.

Сервер слушает ТОЛЬКО 127.0.0.1 и требует токен, который печатается в адресе при
запуске: без него запрос отклоняется. Это защита от чужих страниц в браузере —
они не могут узнать токен, а значит и дёрнуть прогон или прочитать настройки.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):  # запуск файлом: python webapp.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "videobrief"

from . import appconfig, local_llm, media, pipeline  # noqa: E402
from .config import settings as env_settings  # noqa: E402

UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")
TOKEN = secrets.token_urlsafe(16)

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_current: str | None = None


def _new_job(url: str) -> dict:
    return {"id": uuid.uuid4().hex[:12], "url": url, "status": "running",
            "steps": ["Начинаю…"], "error": None, "result": None}


def _run_job(job: dict, values: dict) -> None:
    """Прогон в фоне. Шаги копятся в job['steps'] — окно их опрашивает."""
    global _current

    def step(message: str) -> None:
        job["steps"].append(message)

    opts = pipeline.Options(
        source=job["url"],
        out_root=values.get("out_dir") or appconfig.default_out_dir(),
        audience=values.get("audience") or pipeline.AUDIENCE_DEFAULT,
        mode=values.get("mode") or "auto",
        auto_subs=bool(values.get("auto_subs", True)),
        whisper=values.get("whisper") or env_settings.whisper_model,
        model=values.get("model") or env_settings.model,
        # Разбор доступен и без ключа: локальная модель работает на устройстве.
        analyze=True,
        api_key=values.get("api_key") or None,
        engine=values.get("engine") or env_settings.engine,
        local_url=values.get("local_url") or env_settings.local_url,
        local_model=values.get("local_model") or env_settings.local_model,
    )
    try:
        result = pipeline.run(opts, step)
    except (media.MediaError, RuntimeError, OSError) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
    else:
        job["status"] = "done"
        job["result"] = {
            "out_dir": result.out_dir,
            "title": result.meta.get("title") or "",
            "source_note": result.source_note,
            "brief": result.files.get("brief", ""),
            "clean": result.files.get("clean", ""),
            "timed": result.files.get("timed", ""),
            "analysis_error": result.analysis_error,
            "analyzed": bool(result.brief_path),
            "engine_note": result.engine_note,
        }
        step("Готово")
    finally:
        with _lock:
            _current = None


class Handler(BaseHTTPRequestHandler):
    server_version = "NPBrief"

    def log_message(self, *args) -> None:  # тише в консоли: это не веб-сервер
        pass

    # --- вспомогательное ---

    def _authorized(self, query: dict) -> bool:
        return secrets.compare_digest((query.get("t") or [""])[0], TOKEN)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Окно — единственный клиент; чужим страницам тут делать нечего.
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

    # --- маршруты ---

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
        elif parsed.path == "/api/local":
            # Что сейчас запущено на устройстве: сервер и список моделей.
            try:
                server = local_llm.detect(appconfig.load().get("local_url", ""))
            except local_llm.LocalLLMError as exc:
                self._json({"error": str(exc)})
            else:
                self._json({"base": server.base, "kind": server.kind,
                            "models": server.models})
        elif parsed.path == "/api/state":
            job_id = (query.get("job") or [""])[0]
            self._json({
                "settings": appconfig.masked(appconfig.load()),
                "job": _jobs.get(job_id),
                "busy": _current is not None,
            })
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
                job = _new_job(url)
                _jobs[job["id"]] = job
                _current = job["id"]
            values = appconfig.load()
            values.update({k: body[k] for k in ("mode", "audience") if body.get(k)})
            threading.Thread(target=_run_job, args=(job, values), daemon=True).start()
            self._json({"job": job["id"]})

        elif parsed.path == "/api/settings":
            # Пустой ключ не затирает сохранённый: поле в окне всегда пустое,
            # иначе любое сохранение настроек стирало бы ключ.
            values = {k: v for k, v in body.items() if k != "api_key" or (v or "").strip()}
            self._json({"settings": appconfig.masked(appconfig.save(values))})

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
    """Поднимает окно приложения. port=0 — свободный порт выберет система."""
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

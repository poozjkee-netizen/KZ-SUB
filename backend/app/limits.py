"""Ограничители запросов шлюза: размер тела, одновременность, ключ до разбора.

Зачем модуль, а не пара `if` в main.py: решения здесь чистые (вход — числа и
строки, выход — вердикт), поэтому проверяются dep-free тестами. В main.py
остаётся только тонкая ASGI-обвязка.

Главная защищаемая дыра. FastAPI разбирает multipart ДО тела обработчика:
`file: UploadFile = File(...)` — это зависимость, она выполняется раньше, чем
первая строка `_transcribe`. Значит проверка ключа внутри обработчика уже
поздно: тело целиком прочитано и слито во временный файл на диске. Без
ограничителя любой человек без ключа мог залить сколько угодно гигабайт и
забить диск машины. Поэтому размер и наличие ключа проверяются в middleware —
до разбора формы.

Второй ограничитель — одновременность. Шлюз держит в памяти исходный файл,
конвертированный WAV и base64-куски для Runpod; на 1 ГБ памяти несколько
параллельных больших роликов заканчиваются OOM (это уже случалось, см.
CHANGELOG про 512mb). Плюс у Runpod-эндпоинта конечное число воркеров —
складывать в него больше, чем он тянет, смысла нет.
"""
from __future__ import annotations

import threading

# Эндпоинты, где тело большое и его разбор надо ограничивать заранее.
_GUARDED_PATHS = ("/transcribe",)


def upload_reject(
    method: str,
    path: str,
    content_length: str | None,
    has_api_key: bool,
    max_bytes: int,
) -> tuple[int, str] | None:
    """Вердикт по «сырому» запросу до разбора тела: None — пропустить.

    Возвращает (HTTP-код, текст) для отказа. Коды намеренно те же, что уже
    понимает панель (401/413), чтобы пользователь видел осмысленное сообщение,
    а не «ошибка сервера».
    """
    if method.upper() != "POST" or not path.startswith(_GUARDED_PATHS):
        return None

    # Ключ проверяем здесь же: иначе тело будет прочитано до проверки лицензии.
    if not has_api_key:
        return 401, "Требуется заголовок X-API-Key"

    if content_length is None:
        # Без Content-Length нельзя узнать размер заранее, а читать «сколько
        # придёт» — это и есть незакрытая дыра. Панель заголовок всегда ставит.
        return 411, "Требуется заголовок Content-Length"

    try:
        size = int(content_length)
    except ValueError:
        return 400, "Некорректный Content-Length"
    if size < 0:
        return 400, "Некорректный Content-Length"
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        return 413, f"Файл слишком большой (максимум {mb} МБ)"
    return None


class JobGate:
    """Пропускает не больше N обработок одновременно и одну на ключ.

    Одна на ключ — потому что панель и так шлёт по одному ролику за раз:
    несколько параллельных запросов с одним ключом означают либо ошибку, либо
    попытку занять сервер целиком. Общий лимит бережёт память шлюза и очередь
    Runpod.

    Синхронная реализация на threading: вызывается из синхронного кода и из
    `run_in_threadpool`, а состояние живёт в процессе. При нескольких машинах
    Fly лимит становится «на машину» — этого достаточно, пока машина одна
    (`min_machines_running = 1`), и честно отмечено в docs/CAPACITY.md.
    """

    def __init__(self, max_concurrent: int) -> None:
        self._max = max(1, max_concurrent)
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._count = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._count

    def try_acquire(self, key: str) -> tuple[bool, str]:
        """Занять слот. (True, "") — можно работать; (False, причина) — отказ."""
        with self._lock:
            if key and key in self._active:
                return False, "duplicate"
            if self._count >= self._max:
                return False, "busy"
            self._count += 1
            if key:
                self._active.add(key)
            return True, ""

    def release(self, key: str) -> None:
        with self._lock:
            if self._count > 0:
                self._count -= 1
            self._active.discard(key)

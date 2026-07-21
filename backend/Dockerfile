# KZ-SUB API — CPU-образ.
# Для GPU (быстрее в разы) используйте Dockerfile.gpu.
FROM python:3.12-slim

# ffmpeg — декодирование аудио; libgomp1 — для ctranslate2 (движок faster-whisper).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Дефолты можно переопределить через -e при запуске.
ENV KZSUB_DEVICE=cpu \
    KZSUB_COMPUTE_TYPE=int8 \
    KZSUB_WHISPER_MODEL=large-v3

EXPOSE 8000

# Один воркер: модель держит память, масштабируемся горизонтально (реплики).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

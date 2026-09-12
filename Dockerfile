FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential wget && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/models && \
    wget -q -O /app/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT}"]

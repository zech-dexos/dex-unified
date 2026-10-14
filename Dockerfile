FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential wget && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/models/heretic && \
    wget -q -O /app/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf && \
    wget -q -O /app/models/heretic/model_q4_k_m.gguf \
    https://huggingface.co/tinyopsec/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored-GGUF/resolve/main/model_q4_k_m.gguf && \
    echo "0c90de6859205a9df55663b42dba96e1bbb8157cf41234ce462afd414c68f956  /app/models/heretic/model_q4_k_m.gguf" | sha256sum -c -

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT}"]

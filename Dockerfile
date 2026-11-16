FROM python:3.12-slim

# Node.js + Claude Code CLI (the bot calls `claude -p` for slip reading and analysis)
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 bot \
 && mkdir -p /data \
 && chown bot:bot /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER bot
ENV PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1 \
    DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

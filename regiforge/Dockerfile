FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    OPENAI_SENTINEL_NODE_PATH=/usr/bin/node

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg nodejs xauth xvfb fonts-liberation fonts-noto-cjk \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 regiforge \
    && mkdir -p /app/data \
    && chown -R regiforge:regiforge /app

USER regiforge

EXPOSE 8787

CMD ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", "python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8787"]

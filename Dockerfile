FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Tools yang berguna buat agent: ffmpeg (olah video/audio), git, ca-certificates, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Wajib non-root: mode bypassPermissions Claude Code menolak jalan sebagai root
RUN useradd -m -u 1000 agent

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Folder config Claude (sesi/memori) & folder kerja, dimiliki user non-root
RUN mkdir -p /home/agent/.claude /app/workspace \
    && chown -R agent:agent /home/agent /app

USER agent

CMD ["python", "bot.py"]

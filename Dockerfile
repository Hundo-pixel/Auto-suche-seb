# Lokaler Scraper (z. B. Raspberry Pi 4/5, 64-bit) – nützlich, wenn Portale GitHub-Actions-IPs blocken.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates openssh-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scraper/requirements.txt scraper/requirements.txt
RUN pip install --no-cache-dir -r scraper/requirements.txt
COPY . .
RUN python scraper/tools/fetch_clip.py || echo "CLIP optional – Heuristik wird genutzt"
# Standard: einmal scrapen und über den Branch "data" veröffentlichen (Zeitplan per cron/systemd-Timer auf dem Host)
CMD ["bash", "scraper/tools/local_publish.sh"]

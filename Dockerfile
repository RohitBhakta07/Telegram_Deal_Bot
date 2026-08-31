FROM python:3.11-slim

LABEL org.opencontainers.image.title="Deal Hunter Bot"
LABEL org.opencontainers.image.description="Telegram deal automation bot with adaptive flash detection"
LABEL org.opencontainers.image.version="3.0"

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and Chromium
RUN pip install --no-cache-dir playwright && \
    playwright install chromium && \
    playwright install-deps chromium

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Expose dashboard port
EXPOSE 8000

# Run the bot
CMD ["python", "main.py"]

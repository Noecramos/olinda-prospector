# ─── Stage 1: Build ───────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for Playwright / asyncpg compile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime system libs required by Chromium (manually listed to avoid
# Playwright's --with-deps which pulls unavailable font packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrender1 \
    libxtst6 \
    libfontconfig1 \
    libfreetype6 \
    fonts-liberation \
    fonts-dejavu-core \
    libpq5 \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Install Playwright + Chromium browser (without --with-deps to avoid missing packages)
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Expose dashboard port
EXPOSE 8080

# Non-root user for security
RUN useradd -m prospector
USER prospector

CMD ["python", "main.py"]

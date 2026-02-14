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

# Install Playwright browsers into a portable location
ENV PLAYWRIGHT_BROWSERS_PATH=/build/pw-browsers
RUN pip install --no-cache-dir playwright==1.49.1 \
    && python -m playwright install --with-deps chromium

# ─── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime system libs required by Chromium
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
    fonts-liberation \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /build/pw-browsers /app/pw-browsers

ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers

# Copy application code
COPY . .

# Expose dashboard port
EXPOSE 8080

# Non-root user for security
RUN useradd -m prospector
USER prospector

CMD ["python", "main.py"]

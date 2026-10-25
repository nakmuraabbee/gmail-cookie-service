FROM python:3.10-slim

# Install Chromium and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set Chrome binary environment variable
ENV CHROME_PATH=/usr/bin/chromium

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium

# Copy all project files
COPY . .

# Expose default port
EXPOSE 5000

# Start gunicorn web server
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 server:app"]

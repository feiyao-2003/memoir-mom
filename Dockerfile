FROM python:3.11-slim

# Install system dependencies for weasyprint
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Set working directory to backend
WORKDIR /app/backend

EXPOSE 8000

ENV PORT=8000

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}

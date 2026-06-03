# Jetson Xavier NX friendly image: Python 3.10 on Ubuntu 20.04.
FROM nvcr.io/nvidia/l4t-base:r35.4.1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates \
    gnupg \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libsqlite3-0 \
    espeak-ng \
    python3.10 \
    python3.10-dev \
    python3.10-distutils \
    python3-pip \
    && python3.10 -m pip install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python3.10 -m pip install -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["python3.10", "-m", "stockstream.app"]

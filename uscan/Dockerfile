FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Tesseract does the OCR. Add more languages with e.g. tesseract-ocr-fil and set OCR_LANG=eng+fil.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

# Never run the app as root.
RUN useradd --create-home --uid 10001 uscan && mkdir /data && chown uscan /data
WORKDIR /app

COPY requirements.txt .
RUN grep -viE '^(pytest|httpx)' requirements.txt > runtime.txt && pip install -r runtime.txt

COPY --chown=uscan . .
USER uscan

# Public-site defaults. Override any of them with environment variables on your host.
ENV PUBLIC_MODE=true \
    USCAN_HOST=0.0.0.0 \
    COOKIE_SECURE=true \
    TRUSTED_PROXIES=* \
    DATA_DIR=/data

VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % (os.getenv('USCAN_PORT') or os.getenv('PORT') or '8000'), timeout=4)"
CMD ["python", "run.py"]

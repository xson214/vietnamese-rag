FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer fonts-dejavu fonts-liberation tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
COPY backend/requirements-neural.lock ./requirements-neural.lock
RUN pip install --no-cache-dir -r requirements.lock
ARG INSTALL_NEURAL=true
RUN if [ "$INSTALL_NEURAL" = "true" ]; then pip install --no-cache-dir 'torch==2.15.0' --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements-neural.lock; fi
COPY backend/app ./app
RUN useradd --create-home rag && mkdir -p /data && chown rag:rag /data
USER rag
ENV DATA_DIR=/data OCR_DATA_DIR=/usr/share/tesseract-ocr/5/tessdata
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

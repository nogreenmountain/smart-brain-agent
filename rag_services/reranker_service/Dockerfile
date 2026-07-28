FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cu118 torch==2.3.1 && \
    pip install \
    fastapi==0.115.6 \
    "uvicorn[standard]==0.34.0" \
    transformers==4.44.2 \
    sentence-transformers==3.0.1 \
    FlagEmbedding==1.3.5

COPY rag_services/reranker_service/main.py /app/main.py

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

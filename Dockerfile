FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf
WORKDIR /srv
COPY requirements.txt .
# CPU-only torch keeps the image small; then everything else
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt
# Bake the embedding model into the image so startup needs no download
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

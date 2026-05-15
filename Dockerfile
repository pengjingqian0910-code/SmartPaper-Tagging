FROM python:3.11-slim

WORKDIR /app

# 系統依賴（pdfplumber / lxml 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    libxml2 \
    libxslt1.1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安裝 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 先複製需求檔以利 layer 快取
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# 預下載 ML 模型（build 時下載，執行時不需網路）
RUN python - <<'PYEOF'
print("Pre-downloading ML models...", flush=True)
try:
    from sentence_transformers import CrossEncoder
    CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    print("  [OK] CrossEncoder", flush=True)
except Exception as e:
    print(f"  [WARN] CrossEncoder: {e}", flush=True)

try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    print("  [OK] multilingual MiniLM", flush=True)
except Exception as e:
    print(f"  [WARN] multilingual: {e}", flush=True)

try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("allenai-specter")
    print("  [OK] specter", flush=True)
except Exception as e:
    print(f"  [WARN] specter: {e}", flush=True)
PYEOF

# 複製應用程式程式碼
COPY . .

# 建立資料目錄
RUN mkdir -p data

# Flet Web 模式預設 8550
EXPOSE 8550

# 環境變數（由 docker-compose 或 -e 傳入）
ENV GEMINI_API_KEY=""
ENV CROSSREF_EMAIL=""

CMD ["python", "main.py", "ui-web"]

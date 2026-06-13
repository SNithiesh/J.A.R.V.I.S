FROM python:3.12-slim
WORKDIR /srv
<<<<<<< HEAD

# Node.js (for MCP servers that run via npx, e.g. filesystem, github).
# Installed alongside Python so `npx -y @modelcontextprotocol/server-*` works.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# uv/uvx: runs Python-based MCP servers (fetch, git) on demand
RUN pip install --no-cache-dir uv
=======
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
# Pre-download the embedding model at BUILD time (keep in sync with EMBEDDING_MODEL)
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

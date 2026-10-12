# ---- stage 1: Node + the OpenUI tools for the rich weekly digest (docs/AUTOMATIONS.md section 6)
FROM node:20-bookworm-slim AS openui
WORKDIR /srv/tools/openui
ENV OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1
COPY tools/openui/package.json tools/openui/package-lock.json ./
RUN npm ci --omit=dev
COPY tools/openui/ ./

# ---- stage 2: the app (the base tag pins the same Debian release as the node stage)
FROM python:3.11-slim-bookworm
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the embedding model into the image so cold starts never download it.
ENV FASTEMBED_CACHE_PATH=/models
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
COPY app ./app
COPY static ./static
# The node binary and the installed OpenUI tools from stage 1: the digest e-mail is rendered to HTML with them.
COPY --from=openui /usr/local/bin/node /usr/local/bin/node
COPY --from=openui /srv/tools/openui ./tools/openui
ENV DIGEST_NODE=/usr/local/bin/node
EXPOSE 8080
# One worker: the rate limiter and crawl scheduler are in-process. Scale with a bigger box first.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

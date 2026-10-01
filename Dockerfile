# Lambda container image for the weather poller. Built for arm64 (Graviton), single-manifest so
# Lambda accepts it.
#   ingest.handler.ingest    (default)  hourly, polls every product and publishes freshness
#   ingest.handler.compact              hourly, merges small curated files
FROM public.ecr.aws/lambda/python:3.12

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
ENV UV_SYSTEM_PYTHON=1 UV_NO_CACHE=1

WORKDIR ${LAMBDA_TASK_ROOT}

# Third-party dependencies first, so code changes do not invalidate this layer.
COPY pyproject.toml uv.lock ./
COPY lake/pyproject.toml lake/README.md ./lake/
RUN uv export --frozen --no-dev --all-packages --no-emit-workspace --no-hashes \
      -o /tmp/requirements.txt \
 && uv pip install --target ${LAMBDA_TASK_ROOT} -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The library the pipeline imports its contract from, then the pipeline itself.
COPY lake/src/ ./lake/src/
RUN uv pip install --target ${LAMBDA_TASK_ROOT} --no-deps ./lake && rm -rf ./lake
COPY config.yaml ./
COPY ingest/ ./ingest/

CMD ["ingest.handler.ingest"]

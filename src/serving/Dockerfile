# Serving + batch image. Also used by the Airflow DAG for the drift, retrain and
# promote pods, so it carries the full src/ package and its dependencies.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install a CPU-only torch from PyTorch's CPU index. The PyPI linux wheel pulls the
# full CUDA runtime (~3GB of nvidia-* packages) which this image never uses, so torch
# is installed here and filtered out of the requirements pass below.
ARG TORCH_VERSION=2.9.1
RUN pip install --no-cache-dir "torch==${TORCH_VERSION}" \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN grep -viE '^torch==' requirements.txt > /tmp/requirements-nontorch.txt \
    && pip install --no-cache-dir -r /tmp/requirements-nontorch.txt \
    && rm -rf /root/.cache/pip

COPY src/ ./src/

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "src.serving.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

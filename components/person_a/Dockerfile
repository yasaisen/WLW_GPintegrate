ARG PERSON_A_RUNTIME_BASE=python:3.11-slim-bookworm@sha256:2fc9207f64226cb05ac317cee0bab6fa55a9ea311ce5a086baddd4b4a83c2d3c
FROM ${PERSON_A_RUNTIME_BASE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HF_HOME=/models/huggingface \
    TOKENIZERS_PARALLELISM=false \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CUDA userspace comes from the pinned PyTorch wheel. The host supplies only
# the NVIDIA driver and Container Toolkit.
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    --retries 10 --timeout 120 \
    torch==2.6.0 torchvision==0.21.0 \
    --index-url https://download.pytorch.org/whl/cu124 \
    --extra-index-url https://pypi.org/simple

COPY components/person_a/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    --retries 10 --timeout 120 \
    -r /tmp/requirements.txt

COPY contracts /app/contracts
COPY components/person_a /app/components/person_a
RUN touch /app/components/__init__.py \
    && mkdir -p /models/huggingface

ENTRYPOINT ["python", "-m", "components.person_a.report_decompose"]

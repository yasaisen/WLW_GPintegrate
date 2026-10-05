# Person C (丙) interest pattern extraction.
# Build context is the repository root:
#   docker build -f components/person_c/Dockerfile -t wlw/person-c:0.1.0 .
# No weights, WSIs or run data are baked in: mount reference/ read-only at /reference and
# run/ at /run. Base image follows person_e (nvidia/cuda runtime); Ubuntu 24.04 is used because
# it ships Python 3.12. The host GPU driver (NVIDIA container toolkit) must support CUDA 13.
FROM nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY components/person_c/requirements.txt /tmp/requirements.txt
RUN pip install torch==2.14.0 torchvision==0.29.0 \
      --index-url https://download.pytorch.org/whl/cu130 \
      --extra-index-url https://pypi.org/simple \
    && pip install -r /tmp/requirements.txt

COPY contracts /app/contracts
COPY components/__init__.py /app/components/__init__.py
COPY components/person_c /app/components/person_c
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "-m", "components.person_c.interest_pattern"]

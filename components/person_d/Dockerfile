FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       git libopenslide0=3.4.1+dfsg-5build1 python3 python3-pip python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Ubuntu's pip 22.0.2 builds CONCH's PEP 621 metadata with project name "unknown".
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check pip==25.2
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check \
      torch==2.11.0+cu128 torchvision==0.26.0+cu128 \
      --index-url https://download.pytorch.org/whl/cu128
COPY components/person_d/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check \
      -r /tmp/requirements.txt
COPY contracts /app/contracts
COPY components/person_d /app/components/person_d
RUN touch /app/components/__init__.py
# torch derives the default inductor cache from the user name, which fails for a UID without a
# passwd entry (integration/compose.yaml runs as LOCAL_UID). torch only creates this empty
# directory below run/cache/person_d; nothing is compiled, so no cache files are written.
ENV PYTHONPATH=/app \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCHINDUCTOR_CACHE_DIR=/run/cache/person_d/torchinductor
ENTRYPOINT ["python3", "-m", "components.person_d.visual_filter"]

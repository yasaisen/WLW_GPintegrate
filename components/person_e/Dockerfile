FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       libopenslide0 python3 python3-pip python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY components/person_e/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check \
      torch==2.6.0+cu118 --index-url https://download.pytorch.org/whl/cu118 \
      --extra-index-url https://pypi.org/simple \
    && python3 -m pip install --no-cache-dir --disable-pip-version-check \
      -r /tmp/requirements.txt
COPY contracts /app/contracts
COPY components/person_e /app/components/person_e
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python3", "-m", "components.person_e.clee"]

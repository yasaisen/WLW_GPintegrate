FROM python:3.12-slim
WORKDIR /app
COPY components/person_c/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore -r /tmp/requirements.txt
COPY contracts /app/contracts
COPY components/person_c /app/components/person_c
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "components.person_c.interest_pattern"]

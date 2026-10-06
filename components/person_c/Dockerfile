FROM python:3.12-slim
WORKDIR /app
COPY contracts /app/contracts
COPY components/person_c /app/components/person_c
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "components.person_c.interest_pattern"]

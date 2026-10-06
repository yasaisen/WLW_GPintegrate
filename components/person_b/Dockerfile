FROM python:3.12-slim
WORKDIR /app
COPY contracts /app/contracts
COPY components/person_b /app/components/person_b
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "components.person_b.knowledge_retrieval"]

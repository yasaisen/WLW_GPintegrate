FROM python:3.12-slim
WORKDIR /app
COPY contracts /app/contracts
COPY components/person_d /app/components/person_d
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "components.person_d.visual_filter"]

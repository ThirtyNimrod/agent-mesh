FROM python:3.12-slim
WORKDIR /app

COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY agent/ ./agent/

ENV PYTHONPATH=/app
CMD ["python", "-m", "agent.orchestrator"]

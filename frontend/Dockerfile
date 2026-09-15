FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Container security hardening: run as unprivileged user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /home/appuser/.streamlit && \
    chown -R appuser:appuser /app /home/appuser

USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]

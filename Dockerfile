FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY data/mms-2026-01.json ./data/mms-2026-01.json
COPY data/kb.jsonl* ./data/
ENTRYPOINT ["python", "src/coder.py"]

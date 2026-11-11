FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY emergency_center/ ./emergency_center/

CMD ["python", "emergency_center/main.py"]

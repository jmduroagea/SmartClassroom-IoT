# Same Python and Debian as the Raspberry Pis (Raspbian 11 = Debian bullseye, Python 3.9)
FROM python:3.9-slim-bullseye

ENV TZ=Europe/Paris \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements-brain.txt .
RUN pip install --no-cache-dir -r requirements-brain.txt

# Never run as root inside the container
RUN useradd --create-home app
USER app

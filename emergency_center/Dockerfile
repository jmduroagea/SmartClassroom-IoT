FROM python:3.10-slim
WORKDIR /app

# Especificar la ruta de origen correcta basada en el context raíz
COPY emergency_center/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY emergency_center/main.py .

# El flag -u evita que Python retenga los prints en caché, para verlos en vivo en Docker
CMD ["python", "-u", "main.py"]

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

### TODO: qnd for pra prod tem q usar fastapi run ao inves de fastapi dev pra tirar o reload (acho?)
CMD ["fastapi", "dev", "app/main.py", "--port", "8000"]

# Образ сервиса заявок (ДЗ 2): приложение в контейнере, py-spy внутри образа.
FROM python:3.14.7-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY db ./db
COPY scripts ./scripts
# Один процесс uvicorn: в контейнере у него PID 1, к нему подключается py-spy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

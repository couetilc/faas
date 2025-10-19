FROM python:3.11-slim

WORKDIR /app

COPY handler.py /app/handler.py

RUN chmod +x /app/handler.py

CMD ["python3", "/app/handler.py"]

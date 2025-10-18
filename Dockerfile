FROM python:3.11-slim

WORKDIR /app

# Copy the handler script
COPY docker_handler.py /app/docker_handler.py
RUN chmod +x /app/docker_handler.py

# Run the handler
CMD ["python3", "/app/docker_handler.py"]

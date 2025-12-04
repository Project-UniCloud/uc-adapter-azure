FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN useradd -r -u 1001 adapteruser

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Change ownership to non-root user
RUN chown -R adapteruser:adapteruser /app

USER adapteruser

# Expose the gRPC port
EXPOSE 50053

# Run the adapter
ENTRYPOINT ["python", "main.py"]





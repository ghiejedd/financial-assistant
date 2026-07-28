FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create exports directory
RUN mkdir -p exports

# Expose FastAPI port
EXPOSE 8000

# Run main application
CMD ["python", "main.py"]

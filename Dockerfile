FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY special_days ./special_days

# Generated files (e.g. .xlsx) are written here; mount a volume to retrieve them.
RUN mkdir -p /app/out

ENTRYPOINT ["python", "-m", "special_days"]
CMD ["--help"]

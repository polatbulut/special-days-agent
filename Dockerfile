FROM python:3.12-slim

WORKDIR /app

# Note: THY internal OBS uploads against .thy.com endpoints need the proprietary
# `thy` package at runtime (specifically thy.s3.ThyS3Service). The external THY
# workbench and THY-managed base images provide it; this stock local Dockerfile
# does not.

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY special_days ./special_days

# Generated files (e.g. .xlsx) are written here; mount a volume to retrieve them.
RUN mkdir -p /app/out

ENTRYPOINT ["python", "-m", "special_days"]
CMD ["--help"]

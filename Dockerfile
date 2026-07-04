# WIRE backend API (FastAPI + Playwright). Builds an image that can both serve
# the API and run browser-driven reconstruction.
FROM python:3.11-slim-bookworm

# Browsers install to a shared path so the non-root runtime user can find them.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package first (leverages layer caching for deps).
COPY pyproject.toml README.md ./
COPY wire ./wire
RUN pip install --upgrade pip && pip install .

# Install Chromium matched to the installed Playwright version, plus its OS
# runtime libraries; make the browser dir readable by the runtime user.
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /opt/pw-browsers

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 wire
USER wire

EXPOSE 8000

# JWT_SECRET_KEY, WIRE_CORS_ORIGINS, DATABASE_URL, GEMINI_API_KEY are supplied
# at runtime (see .env.example). Do not bake secrets into the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/status').status==200 else 1)"

CMD ["uvicorn", "wire.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

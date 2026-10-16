FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY bff ./bff
COPY contracts ./contracts
RUN pip install . && groupadd -g 10001 bff && useradd -u 10001 -g bff -M bff && mkdir /data && chown bff:bff /data
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/healthz',timeout=3)"]
CMD ["uvicorn", "bff.app:app", "--host", "0.0.0.0", "--port", "8081", "--no-proxy-headers", "--no-access-log"]

ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

RUN python -m pip install --upgrade pip setuptools wheel packaging

COPY pyproject.toml .
COPY semsearch/ semsearch/
COPY config/ config/

RUN python -m pip install --no-cache-dir .

ENV SEMSEARCH_CONFIG=/data/semsearch.yaml
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /data

EXPOSE 8088

CMD ["semsearch-server"]
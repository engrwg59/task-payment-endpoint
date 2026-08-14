# Production image. Built in two stages so the runtime carries the application
# and nothing that was only needed to install it.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl serves the container healthcheck declared in compose.yml.
RUN apt-get update \
 && apt-get install --no-install-recommends --yes curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 payments

WORKDIR /srv

# The application itself lives in the virtualenv; only the files that have to be
# resolved from the working directory are copied alongside it.
COPY --from=builder /opt/venv /opt/venv
COPY migrations ./migrations
COPY wsgi.py ./

USER payments

EXPOSE 8000

# exec, so gunicorn becomes PID 1 and receives SIGTERM directly on shutdown.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-4} --access-logfile - wsgi:app"]

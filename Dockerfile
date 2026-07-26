# Couvert API container. Build from couvert-backend/:
#   docker build -t couvert-api .
#   docker run -p 5000:5000 --env-file .env couvert-api
#
# Two stages so the runtime image carries no build tooling and no uv.
FROM python:3.12-slim AS builder

# Pinned to the version that produced uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies only, straight from the lockfile — nothing is resolved at build
# time. The project itself is not installed: `jobs/` is excluded from the image
# (see .dockerignore) and pyproject lists it as a package, so installing would
# fail. Running from /app makes `api` and `core` importable anyway.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev


FROM python:3.12-slim AS runtime

# Non-root: the app never writes to disk.
RUN useradd --create-home --uid 10001 couvert
WORKDIR /app

COPY --from=builder --chown=couvert:couvert /app/.venv /app/.venv
COPY --chown=couvert:couvert core ./core
COPY --chown=couvert:couvert api ./api

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER couvert
EXPOSE 5000

# One worker: the app is async and IO-bound, and Container Apps scales by adding
# replicas rather than processes. --proxy-headers so request URLs reflect the
# ingress scheme (https) rather than the container's http.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "5000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

# Batch job, not a service. Build, run, collect the artifact.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so source edits do not invalidate the layer. README is
# here because pyproject declares it as the package readme, and hatchling
# refuses to build without it.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src/ src/
COPY configs/ configs/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# No default command: `ingest` touches the network and writes, `backtest` does
# neither. Which one runs is the caller's decision.
ENTRYPOINT ["qrt"]
CMD ["--help"]

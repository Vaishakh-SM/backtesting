.PHONY: install lint types test check ingest backtest clean

install:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

types:
	uv run mypy

test:
	uv run pytest

check: lint types test

# Touches the network. Everything else runs offline.
ingest:
	uv run backtester ingest --universe configs/universe.yaml

backtest:
	uv run backtester run configs/momentum.yaml

clean:
	rm -rf out .pytest_cache .ruff_cache .mypy_cache

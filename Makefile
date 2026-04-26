.PHONY: all test lint fmt type-check install clean benchmark evals

all: lint test

install:
	pip install -e ".[all,dev]"

test:
	python -m pytest tests/ -v --tb=short --cov=mcp_toolkit --cov-report=term-missing --cov-fail-under=88

lint:
	ruff check .

fmt:
	ruff format .

type-check:
	pyright .

benchmark:
	python benchmarks/bench_cache.py

evals:
	python evals/run_evals.py --verbose

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

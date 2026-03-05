.PHONY: all test lint fmt type-check install clean

all: lint test

install:
	pip install -e ".[all,dev]"

test:
	python -m pytest tests/ -v --tb=short

lint:
	ruff check .

fmt:
	ruff format .

type-check:
	pyright .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

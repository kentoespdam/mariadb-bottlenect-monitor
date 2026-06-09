.PHONY: all install dev install-dev lint format check test test-cov clean run docker-build docker-up docker-down

UV := uv
PYTHON := python
SRC := src
TESTS := tests

all: check

# --- Dependencies ---

install:
	$(UV) sync

dev install-dev:
	$(UV) sync --group dev

# --- Lint & Format ---

lint:
	$(UV) run ruff check $(SRC) $(TESTS)

format:
	$(UV) run ruff format $(SRC) $(TESTS)

check: lint format-check

format-check:
	$(UV) run ruff format --check $(SRC) $(TESTS)

# --- Test ---

test:
	$(UV) run python -m pytest $(TESTS) -v

test-cov:
	$(UV) run python -m pytest $(TESTS) -v --cov=$(SRC) --cov-report=term-missing

# --- Run ---

run:
	$(UV) run python -m $(SRC)

# --- Docker ---

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

# --- Clean ---

clean:
	rm -rf .pytest_cache
	rm -rf $(SRC)/*.egg-info
	rm -rf $(SRC)/__pycache__
	rm -rf $(TESTS)/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

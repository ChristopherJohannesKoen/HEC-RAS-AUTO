.PHONY: init lint test fmt pipeline-baseline

init:
	pip install -e .[dev]

lint:
	ruff check src tests
	mypy src

test:
	pytest

pipeline-baseline:
	ras-auto init
	ras-auto ingest --config config/project.yml
	ras-auto complete-xs --chainage 0 --run-id baseline
	ras-auto build-geometry --run-id baseline
	ras-auto prepare-run --run-id baseline

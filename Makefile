.PHONY: all
all: build-format

.PHONY: build
build:
	python script/build.py

.PHONY: build-format
build-format: build
	ruff format dist/
	ruff check --fix dist/

.PHONY: lint
lint:
	ruff check --fix .

.PHONY: format
format:
	ruff format .

.PHONY: lint-format
lint-format: lint format

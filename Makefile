# Thin wrappers — delegates to scripts/dev.py for cross-platform compatibility (Windows + Unix).
# On Unix you can use `make <target>`; on Windows run `python scripts/dev.py <target>` directly.

.PHONY: up down install migrate seed count-rows check-health test verify verify-schema

up:
	python scripts/dev.py up

down:
	python scripts/dev.py down

install:
	python scripts/dev.py install

migrate:
	python scripts/dev.py migrate

seed:
	python scripts/dev.py seed

count-rows:
	python scripts/dev.py count-rows

check-health:
	python scripts/dev.py check-health

test:
	python scripts/dev.py test

verify:
	python scripts/dev.py verify

verify-schema:
	python scripts/dev.py verify-schema

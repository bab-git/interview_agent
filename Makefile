PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn

.PHONY: install run test demo smoke format

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000

test:
	$(PYTEST)

demo:
	$(VENV)/bin/python scripts/demo_flow.py

smoke:
	$(VENV)/bin/python scripts/live_smoke_test.py --base-url http://127.0.0.1:8000

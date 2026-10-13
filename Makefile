PY ?= python

.PHONY: dev test check benchmark spike install

install:
	$(PY) -m pip install -r requirements-dev.txt

dev:
	$(PY) -m uvicorn vare.main:app --reload --port 8000

test:
	$(PY) -m pytest tests/ -q

check:
	$(PY) tools/check_secrets.py && $(PY) tools/check_publishable.py

benchmark:
	$(PY) tools/benchmark.py

spike:
	$(PY) scripts/qloo_spike.py


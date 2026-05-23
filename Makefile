.PHONY: install run

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

run:
	./run.sh

# Convenience targets for the venv and Docker workflows.
# Pass CLI args via ARGS, e.g.:  make run ARGS="--agent turkey --source holidays"

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
IMAGE := special-days-agent
ARGS ?= --help

.PHONY: venv test run docker-build docker-run clean

venv:                ## Create the virtualenv and install dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

test: venv           ## Run the test suite inside the venv
	$(PY) -m unittest discover -s tests

run: venv            ## Run the CLI inside the venv (ARGS="...")
	$(PY) -m special_days $(ARGS)

docker-build:        ## Build the Docker image
	docker build -t $(IMAGE) .

docker-run: docker-build  ## Run the CLI in Docker; .env for keys, ./out for files
	mkdir -p out
	docker run --rm --env-file .env -v "$(PWD)/out:/app/out" $(IMAGE) $(ARGS)

clean:               ## Remove the venv, caches and generated files
	rm -rf $(VENV) out *.xlsx
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

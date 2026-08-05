# Convenience targets for the venv and Docker workflows.
# Pass CLI args via ARGS, e.g.:  make run ARGS="--agent turkey --source holidays"

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
IMAGE := specialevents-schedule
ARGS ?= --help

.PHONY: venv test run case-studies docker-build docker-run clean

venv:                ## Create the virtualenv and install dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

test: venv           ## Run the test suite inside the venv
	$(PY) -m unittest discover -s tests

run: venv            ## Run the CLI inside the venv (ARGS="...")
	$(PY) -m special_days $(ARGS)

# Per-event LF case studies. Offline only: reads two local files, no network,
# no LLM. Start from out/events.template.csv; see docs/case-studies-input.md.
#   make case-studies EVENTS=out/events.csv LF=out/lf_route_day.csv
# Extra flags via CASE_ARGS, e.g. CASE_ARGS="--window-days 21 --lf-sheet LF"
EVENTS ?= out/events.csv
LF ?= out/lf_route_day.csv
OUT ?= out/case_studies
CASE_ARGS ?=

case-studies: venv   ## Build the per-event LF case studies (EVENTS=... LF=... OUT=...)
	$(PY) -m special_days.case_studies --events "$(EVENTS)" --lf "$(LF)" --out "$(OUT)" $(CASE_ARGS)

docker-build:        ## Build the Docker image
	docker build -t $(IMAGE) .

docker-run: docker-build  ## Run the CLI in Docker; .env for keys, ./out for files
	mkdir -p out
	docker run --rm --env-file .env -v "$(PWD)/out:/app/out" $(IMAGE) $(ARGS)

clean:               ## Remove the venv, caches and generated files
	rm -rf $(VENV) out *.xlsx
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

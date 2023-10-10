
SHELL=/bin/bash

BACKTEST_START=2022-1-1
BACKTEST_END=2022-1-31
BACKTEST_OUTPUT=data/dma.pickle

CONDA_ENV_NAME=zipline-tardis-bundle
CONDA_ENV_FILE_DEV=./environment.yml
CONDA_ENV_FILE_PRODUCTION=./environment-frozen.yml
CONDA_DIR=$(HOME)/miniforge3
CONDA_BIN=mamba
CONDA_INSTALL_BIN=$(CONDA_DIR)/bin/$(CONDA_BIN)
CONDA_ACTIVATE=source $(CONDA_DIR)/etc/profile.d/conda.sh; source $(CONDA_DIR)/etc/profile.d/mamba.sh; $(CONDA_BIN) activate $(CONDA_ENV_NAME)

TARDIS_DATA_DIR=./data/tardis_bundle

ZIPLINE_BUNDLE=custom-tardis-bundle
ZIPLINE_DIR=$(HOME)/.zipline
ZIPLINE_STRATEGY=tests/zipline_strategy.py

local-module-install:
	$(CONDA_ACTIVATE); pip install -e ./

conda-env-install:
	$(CONDA_INSTALL_BIN) env create -f $(CONDA_ENV_FILE_DEV)

conda-env-production-install:
	$(CONDA_INSTALL_BIN) env create -f $(CONDA_ENV_FILE_PRODUCTION)

env-dev-install: conda-env-install local-module-install

env-production-install: conda-env-production-install local-module-install

conda-update-dev:
	$(CONDA_INSTALL_BIN) env update -f $(CONDA_ENV_FILE_DEV) --prune

conda-update-production:
	$(CONDA_INSTALL_BIN) env export -n $(CONDA_ENV_NAME)| head -n -1 > $(CONDA_ENV_FILE_PRODUCTION)

conda-update: conda-update-dev conda-update-production

install-mamba:
	scripts/install-mamba.sh; echo 'Launch a new shell to continue... '; read

$(ZIPLINE_DIR)/extension.py: trading_signals/backtesting/extension.py
	mkdir -p $(ZIPLINE_DIR)
	cp trading_signals/backtesting/extension.py $(ZIPLINE_DIR)

install-zipline: $(ZIPLINE_DIR)/extension.py

install-pre-commit:
	$(CONDA_ACTIVATE); pre-commit install

install: env-dev-install install-zipline install-pre-commit jupytext-sync

clean-zipline:
	rm -rf $(ZIPLINE_DIR)/data/$(ZIPLINE_BUNDLE)/*

clean-tardis:
	rm -rf ./data/tardis_bundle/*

clean-all: clean-tardis clean-zipline

create-temp-dir:
	mkdir -p $(TEMP)

ingest: export TEMP=$(ZIPLINE_DIR)/tmp
ingest: export ZIPLINE_TARDIS_DIR=$(TARDIS_DATA_DIR)
ingest: create-temp-dir
	$(CONDA_ACTIVATE); zipline ingest -b $(ZIPLINE_BUNDLE) --no-show-progress

bundles:
	$(CONDA_ACTIVATE); zipline bundles

run:
	$(CONDA_ACTIVATE); \
	zipline run \
		--trading-calendar 24/7 \
		--data-frequency minute \
		--bundle $(ZIPLINE_BUNDLE) \
		-f $(ZIPLINE_STRATEGY) \
		--start $(BACKTEST_START) --end $(BACKTEST_END) \
		-o $(BACKTEST_OUTPUT) \
		--no-benchmark

run-fresh: conda-update install-zipline clean-all ingest run

test-pre-commit:
	$(CONDA_ACTIVATE); pre-commit run --all

test-pytest:
	$(CONDA_ACTIVATE); cd tests; pytest

test: test-pytest test-pre-commit

start-blackd:
	$(CONDA_ACTIVATE); blackd

start-jupyter-lab:
	$(CONDA_ACTIVATE); jupyter-lab --allow-root --ip=0.0.0.0

jupytext-sync:
	$(CONDA_ACTIVATE); jupytext --sync notebooks/*/*.pynb notebooks/*/*.py

conda-build:
	conda mambabuild -c conda-forge -c mesonomics --output-folder . conda/zipline-tardis-bundle

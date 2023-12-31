# zipline-tardis-bundle

[![Conda Test](https://github.com/phelps-sg/zipline-tardis-bundle/actions/workflows/conda_test.yml/badge.svg)](https://github.com/phelps-sg/zipline-tardis-bundle/actions/workflows/conda_test.yml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Anaconda-Server Badge](https://img.shields.io/conda/pn/mesonomics/zipline-tardis-bundle.svg)](https://anaconda.org/mesonomics/zipline-tardis-bundle)
[![Anaconda-Server Badge](https://img.shields.io/conda/v/mesonomics/zipline-tardis-bundle.svg)](https://anaconda.org/mesonomics/zipline-tardis-bundle)
[![Anaconda-Server Badge](https://img.shields.io/conda/l/mesonomics/zipline-tardis-bundle.svg)](https://anaconda.org/mesonomics/zipline-tardis-bundle)
[![Anaconda-Server Badge](https://img.shields.io/conda/dn/mesonomics/zipline-tardis-bundle)](https://anaconda.org/mesonomics/zipline-tardis-bundle)

A [data bundle](https://zipline.ml4trading.io/bundles.html) for [zipline-reloaded](https://zipline.ml4trading.io/) to allow data for crypto assets to be ingested from 
[Tardis](https://tardis.dev/).

## Installation

### 1. Install a conda distribution

If not already installed, install either:

- [Anaconda](https://www.anaconda.com/download/) or,
- [mambaforge](https://github.com/conda-forge/miniforge#mambaforge) (recommended).

### 2. Install the conda package:

Run the following in a shell:

~~~bash
conda install -c mesonomics zipline-tardis-bundle
~~~

### 3. Install the configuration file:

Run the following in a shell:

~~~bash
install-tardis-bundle
~~~

### 4. Configure Zipline settings

- Edit `~/.zipline/extension.py` with appropriate values, and configure your API key.

### 5. Ensure Tardis bundles are available:

Run the following in a shell:

~~~bash
zipline bundles
~~~

This should show some tardis bundles, e.g.:

~~~
custom-tardis-bundle <no ingestions>
tardis-coinbase-since-2019-GBP <no ingestions>
tardis-coinbase-since-2019-USD <no ingestions>
tardis-coinbase-since-2020-GBP <no ingestions>
tardis-coinbase-since-2020-USD <no ingestions>
tardis-coinbase-since-2021-GBP <no ingestions>
tardis-coinbase-since-2021-USD <no ingestions>
tardis-coinbase-since-2022-GBP <no ingestions>
tardis-coinbase-since-2022-USD <no ingestions>
~~~

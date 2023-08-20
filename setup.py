from setuptools import setup, find_packages

setup(
    name="zipline-tardis-bundle",
    version="0.1.0",
    py_modules=['zipline_tardis_bundle'],
    license="MIT",
    author="Steve Phelps",
    author_email="sphelps@sphelps.net",
    description="Zipline bundle to ingest TARDIS data",
    install_requires=['mPyPl', 'tardis-client', 'tardis_dev']
)


conda-build:
	#conda mambabuild --output-folder . --python=3.10 conda/zipline-tardis-bundle
	conda mambabuild -c conda-forge -c sphelps --output-folder . conda/zipline-tardis-bundle

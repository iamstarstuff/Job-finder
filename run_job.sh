#!/bin/bash

# Activate the conda environment
source /Users/pratik/opt/miniconda3/etc/profile.d/conda.sh
conda activate SETU

python /Users/pratik/Github/Job-finder/jobscraper.py

conda deactivate
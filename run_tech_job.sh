#!/bin/bash

# Activate the conda environment
source /Users/pratik/opt/miniconda3/etc/profile.d/conda.sh
cd /Users/pratik/Github/Job-finder
conda activate base
python /Users/pratik/Github/Job-finder/tech_jobs.py
conda deactivate

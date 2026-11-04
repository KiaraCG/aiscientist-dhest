#!/bin/bash
#SBATCH --job-name=take-exam-dhest
#SBATCH --output=logs/exam_%j.out
#SBATCH --error=logs/exam_%j.err
#SBATCH --account=dslab
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G

source .venv/bin/activate

python exam_taker.py
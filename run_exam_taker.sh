#!/bin/bash
#SBATCH --job-name=take-exam-dhest
#SBATCH --output=logs/exam_%j.out
#SBATCH --error=logs/exam_%j.err
#SBATCH --account=dslab
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G

source .venv/bin/activate

# $1 captures the python script name, and shift moves past it 
# so "$@" captures all remaining flags/arguments for your python script.
PYTHON_SCRIPT="$1"
shift

# How to run the script (example):
# sbatch run_exam_taker.sh python solve_exam_a.py --exam_dir signals-and-systems --model CSCS-Inference/swiss-ai/Apertus-v1.5-70B --exam_id 2020_autumn
python "$PYTHON_SCRIPT" "$@"
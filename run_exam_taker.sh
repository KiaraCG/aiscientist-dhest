#!/bin/bash
#SBATCH --job-name=take-exam-dhest
#SBATCH --output=logs/exam_%j.out
#SBATCH --error=logs/exam_%j.err
#SBATCH --account=dslab
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G

source .venv/bin/activate

# Pass any command-line arguments given to sbatch directly to python
# Example: sbatch run_exam_taker.sh --examdir signals-and-systems --model CSCS-Inference/swiss-ai/Apertus-v1.5-70B --examid hs17
python exam_taker.py "$@"
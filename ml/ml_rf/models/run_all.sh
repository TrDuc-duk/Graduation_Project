#!/bin/bash
set -e
cd "/media/trungduc/New Volume/Graduation_Project/ml/ml_rf"
PY=../ml_xgb/.venv/bin/python
echo "=== TUNE $(date)"
$PY -m rf.tune
echo "=== TRAIN $(date)"
$PY -m rf.train --horizons all --params models/tuning/best_params.json --eval-test
echo "=== COMPARE $(date)"
$PY -m rf.compare
echo "=== DONE $(date)"

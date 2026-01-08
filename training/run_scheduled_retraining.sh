#!/bin/bash

##############################################################################
# Scheduled Retraining Script for Atlas Recommendation System
#
# Purpose:
#   Cron-friendly entrypoint for automated model retraining
#
# Features:
#   - Generates timestamped model versions
#   - Logs all output to dated log files
#   - Runs complete training pipeline
#   - Does NOT auto-deploy models (manual validation required)
#
# Usage:
#   ./training/run_scheduled_retraining.sh
#
# Cron Example (Weekly - Sunday 2 AM):
#   0 2 * * 0 cd /path/to/P1 && ./training/run_scheduled_retraining.sh
#
# Cron Example (Monthly - 1st day, 3 AM):
#   0 3 1 * * cd /path/to/P1 && ./training/run_scheduled_retraining.sh
##############################################################################

set -e  # Exit on any error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/training/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
MODEL_VERSION=$(date +"%Y%m%d_%H%M")
LOG_FILE="$LOG_DIR/retraining_${TIMESTAMP}.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Header
echo "============================================================" | tee -a "$LOG_FILE"
echo "Atlas Scheduled Retraining - Started at $(date)" | tee -a "$LOG_FILE"
echo "Model Version: $MODEL_VERSION" | tee -a "$LOG_FILE"
echo "Log File: $LOG_FILE" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Change to project root
cd "$PROJECT_ROOT"

# Activate virtual environment if it exists
if [ -f "training/venv/bin/activate" ]; then
    echo "[INFO] Activating virtual environment..." | tee -a "$LOG_FILE"
    source training/venv/bin/activate
elif [ -f "training/venv/Scripts/activate" ]; then
    echo "[INFO] Activating virtual environment (Windows)..." | tee -a "$LOG_FILE"
    source training/venv/Scripts/activate
else
    echo "[WARNING] No virtual environment found, using system Python" | tee -a "$LOG_FILE"
fi

# Run training pipeline
echo "[INFO] Starting training pipeline with model version: $MODEL_VERSION" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

python training/run_pipeline.py \
    --model-version "$MODEL_VERSION" \
    --config training/config.yaml \
    2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

# Footer
echo "" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Retraining COMPLETED SUCCESSFULLY at $(date)" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    echo "Next Steps:" | tee -a "$LOG_FILE"
    echo "  1. Review artifacts in: training/artifacts/models/$MODEL_VERSION/" | tee -a "$LOG_FILE"
    echo "  2. Validate model performance metrics" | tee -a "$LOG_FILE"
    echo "  3. Manually deploy to production if metrics are acceptable" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    echo "⚠️  MODELS ARE NOT AUTO-DEPLOYED - Manual validation required" | tee -a "$LOG_FILE"
else
    echo "✗ Retraining FAILED with exit code $EXIT_CODE at $(date)" | tee -a "$LOG_FILE"
    echo "Check log file for details: $LOG_FILE" | tee -a "$LOG_FILE"
fi
echo "============================================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE

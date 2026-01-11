"""
Scheduled Event Export Runner

Runs the event export script on a schedule (daily, hourly, or on-demand).

Usage:
    # Run export immediately
    python run_scheduled_export.py --now

    # Run in continuous mode (daily at 2 AM)
    python run_scheduled_export.py --schedule daily

    # Run in continuous mode (every 6 hours)
    python run_scheduled_export.py --schedule hourly --interval 6

    # Run with custom cron expression
    python run_scheduled_export.py --cron "0 2 * * *"

    # Docker container (runs as background service)
    docker run -e SCHEDULE=daily event-exporter

Environment Variables:
    SCHEDULE: daily, hourly, or cron expression
    EXPORT_INTERVAL: Hours between exports (for hourly mode)
    DATABASE_URL: PostgreSQL connection string
"""

import argparse
import logging
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import schedule

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Path to export script
EXPORT_SCRIPT = Path(__file__).parent / 'export_events_to_parquet.py'


def run_export(incremental: bool = True) -> bool:
    """
    Run the export script.
    
    Args:
        incremental: Only export new dates
    
    Returns:
        True if export succeeded, False otherwise
    """
    logger.info("=" * 60)
    logger.info(f"Starting scheduled export at {datetime.now()}")
    logger.info("=" * 60)
    
    cmd = [sys.executable, str(EXPORT_SCRIPT)]
    
    if incremental:
        cmd.append('--incremental')
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        logger.info(result.stdout)
        
        if result.stderr:
            logger.warning(result.stderr)
        
        logger.info("✓ Export completed successfully")
        return True
    
    except subprocess.CalledProcessError as e:
        logger.error(f"Export failed with exit code {e.returncode}")
        logger.error(e.stdout)
        logger.error(e.stderr)
        return False
    
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        return False


def schedule_daily(hour: int = 2, minute: int = 0):
    """Schedule export to run daily at specified time."""
    time_str = f"{hour:02d}:{minute:02d}"
    logger.info(f"Scheduling daily export at {time_str}")
    
    schedule.every().day.at(time_str).do(run_export, incremental=True)
    
    logger.info(f"Next run: {schedule.next_run()}")
    logger.info("Press Ctrl+C to stop")
    
    # Run immediately on startup
    logger.info("Running initial export...")
    run_export(incremental=True)
    
    # Then run on schedule
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def schedule_hourly(interval: int = 6):
    """Schedule export to run every N hours."""
    logger.info(f"Scheduling export every {interval} hours")
    
    schedule.every(interval).hours.do(run_export, incremental=True)
    
    logger.info(f"Next run: {schedule.next_run()}")
    logger.info("Press Ctrl+C to stop")
    
    # Run immediately on startup
    logger.info("Running initial export...")
    run_export(incremental=True)
    
    # Then run on schedule
    while True:
        schedule.run_pending()
        time.sleep(300)  # Check every 5 minutes


def schedule_cron(cron_expression: str):
    """
    Schedule export using cron-like expression.
    
    Note: This is a simplified cron parser for common patterns.
    For full cron support, use system cron or a Docker scheduler.
    """
    logger.warning("Cron expression support is limited. Consider using system cron instead.")
    logger.info(f"Attempting to parse: {cron_expression}")
    
    # Simple parser for "0 2 * * *" (daily at 2 AM)
    parts = cron_expression.split()
    
    if len(parts) != 5:
        logger.error("Invalid cron expression. Expected 5 fields: minute hour day month weekday")
        return
    
    minute, hour, day, month, weekday = parts
    
    # Only support daily at specific time for now
    if day == '*' and month == '*' and weekday == '*':
        try:
            hour_int = int(hour)
            minute_int = int(minute)
            schedule_daily(hour_int, minute_int)
        except ValueError:
            logger.error("Invalid hour/minute in cron expression")
    else:
        logger.error("Only daily schedules (day=*, month=*, weekday=*) are supported")


def main():
    parser = argparse.ArgumentParser(
        description='Scheduled event export runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--now',
        action='store_true',
        help='Run export immediately and exit'
    )
    
    parser.add_argument(
        '--schedule',
        type=str,
        choices=['daily', 'hourly'],
        help='Run on schedule (daily or hourly)'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=6,
        help='Hours between exports (for hourly mode). Default: 6'
    )
    
    parser.add_argument(
        '--time',
        type=str,
        default='02:00',
        help='Time for daily export (HH:MM). Default: 02:00'
    )
    
    parser.add_argument(
        '--cron',
        type=str,
        help='Cron expression (e.g., "0 2 * * *")'
    )
    
    parser.add_argument(
        '--no-incremental',
        action='store_true',
        help='Export all dates (not just new ones)'
    )
    
    args = parser.parse_args()
    
    try:
        # Immediate run
        if args.now:
            success = run_export(incremental=not args.no_incremental)
            return 0 if success else 1
        
        # Scheduled runs
        if args.schedule == 'daily':
            hour, minute = map(int, args.time.split(':'))
            schedule_daily(hour, minute)
        
        elif args.schedule == 'hourly':
            schedule_hourly(args.interval)
        
        elif args.cron:
            schedule_cron(args.cron)
        
        else:
            parser.print_help()
            logger.error("\nError: Must specify --now, --schedule, or --cron")
            return 1
    
    except KeyboardInterrupt:
        logger.info("\nScheduler stopped by user")
        return 0
    
    except Exception as e:
        logger.error(f"Scheduler failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

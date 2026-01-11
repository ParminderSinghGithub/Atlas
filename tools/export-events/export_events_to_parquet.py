"""
Export Events from PostgreSQL to Parquet

Exports events from the PostgreSQL events table to date-partitioned parquet files
for use in the training pipeline.

Usage:
    # Export all events
    python export_events_to_parquet.py

    # Export specific date range
    python export_events_to_parquet.py --start-date 2026-01-10 --end-date 2026-01-11

    # Export incrementally (only new dates)
    python export_events_to_parquet.py --incremental

    # Dry run (show what would be exported)
    python export_events_to_parquet.py --dry-run

Environment Variables:
    DATABASE_URL: PostgreSQL connection string (default: postgresql://postgres:postgres@localhost:5432/ecommerce)
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Get database URL from environment or default."""
    return os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/ecommerce'
    )


def connect_to_database(database_url: str):
    """Create SQLAlchemy engine."""
    logger.info("Connecting to PostgreSQL...")
    engine = create_engine(database_url, poolclass=NullPool)
    return engine


def get_date_range_from_events(engine) -> tuple:
    """Get the min and max date from events table."""
    query = """
        SELECT 
            MIN(DATE(ts)) as min_date,
            MAX(DATE(ts)) as max_date,
            COUNT(*) as total_events
        FROM events
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query)).fetchone()
        
    if result[0] is None:
        logger.warning("No events found in database")
        return None, None, 0
    
    return result[0], result[1], result[2]


def get_existing_export_dates(output_dir: Path) -> set:
    """Get list of dates already exported."""
    if not output_dir.exists():
        return set()
    
    existing_dates = set()
    for date_dir in output_dir.glob('date=*'):
        if date_dir.is_dir():
            date_str = date_dir.name.replace('date=', '')
            try:
                existing_dates.add(datetime.strptime(date_str, '%Y-%m-%d').date())
            except ValueError:
                logger.warning(f"Invalid date directory: {date_dir}")
    
    return existing_dates


def export_events_for_date(engine, export_date: date, output_dir: Path, dry_run: bool = False) -> int:
    """Export events for a specific date to parquet."""
    logger.info(f"Processing date: {export_date}")
    
    # Query events for this date
    query = """
        SELECT 
            event_id,
            event_type,
            user_id,
            session_id,
            product_id,
            properties,
            ts
        FROM events
        WHERE DATE(ts) = :export_date
        ORDER BY ts
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn, params={'export_date': export_date})
    
    # Convert JSONB properties column to string for parquet compatibility
    if 'properties' in df.columns and not df['properties'].isna().all():
        df['properties'] = df['properties'].astype(str)
    
    event_count = len(df)
    
    if event_count == 0:
        logger.info(f"  No events found for {export_date}")
        return 0
    
    if dry_run:
        logger.info(f"  [DRY RUN] Would export {event_count} events")
        return event_count
    
    # Create output directory
    date_dir = output_dir / f'date={export_date}'
    date_dir.mkdir(parents=True, exist_ok=True)
    
    # Save to parquet
    output_file = date_dir / 'events_001.parquet'
    df.to_parquet(output_file, index=False, compression='snappy', engine='pyarrow')
    
    logger.info(f"  ✓ Exported {event_count} events to {output_file}")
    
    return event_count


def export_events(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    incremental: bool = False,
    output_dir: Optional[Path] = None,
    dry_run: bool = False
) -> dict:
    """
    Export events from PostgreSQL to parquet files.
    
    Args:
        start_date: Start date for export (inclusive)
        end_date: End date for export (inclusive)
        incremental: Only export dates not already exported
        output_dir: Output directory for parquet files
        dry_run: Show what would be exported without actually exporting
    
    Returns:
        dict with export statistics
    """
    # Setup
    database_url = get_database_url()
    engine = connect_to_database(database_url)
    
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / 'notebooks' / 'artifacts' / 'events'
    
    logger.info(f"Output directory: {output_dir}")
    
    # Get date range from database
    db_min_date, db_max_date, total_events = get_date_range_from_events(engine)
    
    if db_min_date is None:
        logger.warning("No events in database to export")
        return {'total_events': 0, 'dates_exported': 0}
    
    logger.info(f"Database contains {total_events:,} events from {db_min_date} to {db_max_date}")
    
    # Determine date range to export
    if start_date is None:
        start_date = db_min_date
    if end_date is None:
        end_date = db_max_date
    
    logger.info(f"Export date range: {start_date} to {end_date}")
    
    # Get existing exports if incremental
    existing_dates = set()
    if incremental:
        existing_dates = get_existing_export_dates(output_dir)
        logger.info(f"Found {len(existing_dates)} existing export dates")
    
    # Export each date
    dates_to_export = []
    current_date = start_date
    while current_date <= end_date:
        if not incremental or current_date not in existing_dates:
            dates_to_export.append(current_date)
        current_date += timedelta(days=1)
    
    logger.info(f"Will export {len(dates_to_export)} dates")
    
    if dry_run:
        logger.info("[DRY RUN MODE] - No files will be created")
    
    # Export
    total_exported = 0
    dates_exported = 0
    
    for export_date in dates_to_export:
        count = export_events_for_date(engine, export_date, output_dir, dry_run)
        if count > 0:
            total_exported += count
            dates_exported += 1
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXPORT SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total events exported: {total_exported:,}")
    logger.info(f"Dates exported: {dates_exported}")
    logger.info(f"Output directory: {output_dir}")
    
    if not dry_run:
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Run training pipeline: python training/run_pipeline.py --model-version $(date +%Y%m%d_%H%M%S)")
        logger.info("  2. Or run feature engineering: python training/build_features.py")
    
    return {
        'total_events': total_exported,
        'dates_exported': dates_exported,
        'output_dir': str(output_dir)
    }


def main():
    parser = argparse.ArgumentParser(
        description='Export PostgreSQL events to parquet files for training',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date (YYYY-MM-DD). Default: earliest event in database'
    )
    
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD). Default: latest event in database'
    )
    
    parser.add_argument(
        '--incremental',
        action='store_true',
        help='Only export dates not already exported'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        help='Output directory for parquet files. Default: notebooks/artifacts/events'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be exported without actually exporting'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Parse dates
    start_date = None
    end_date = None
    
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid start date format: {args.start_date}. Use YYYY-MM-DD")
            return 1
    
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid end date format: {args.end_date}. Use YYYY-MM-DD")
            return 1
    
    output_dir = Path(args.output_dir) if args.output_dir else None
    
    try:
        export_events(
            start_date=start_date,
            end_date=end_date,
            incremental=args.incremental,
            output_dir=output_dir,
            dry_run=args.dry_run
        )
        
        return 0
    
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

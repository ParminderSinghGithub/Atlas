#!/usr/bin/env python3
"""
P1 Synthetic User Behavior Simulator - CLI

Usage:
    python run_simulator.py --mode replay --events 1000 --users 50
    python run_simulator.py --mode live --events 500 --rate 10 --seed 123
"""

import argparse
import sys
import time
from pathlib import Path

from tqdm import tqdm

from .generator import BehaviorGenerator


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="P1 Synthetic User Behavior Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 1000 events and save to Parquet files
  python run_simulator.py --mode replay --events 1000 --users 50

  # Generate 500 events and send to API at 10 events/sec
  python run_simulator.py --mode live --events 500 --rate 10

  # Use custom config file and seed
  python run_simulator.py --mode replay --events 5000 --config custom.yaml --seed 42

  # Generate events for specific number of users
  python run_simulator.py --mode replay --events 10000 --users 200 --seed 999
        """,
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        choices=["replay", "live", "kafka"],
        required=True,
        help="Simulation mode: 'replay' writes Parquet files, 'live' sends to API, 'kafka' publishes to Kafka",
    )
    
    parser.add_argument(
        "--events",
        type=int,
        default=1000,
        help="Number of events to generate (default: 1000)",
    )
    
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help="Events per second for live mode (default: from config.yaml)",
    )
    
    parser.add_argument(
        "--users",
        type=int,
        default=None,
        help="Number of unique users to simulate (default: from config.yaml)",
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (default: from config.yaml)",
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for Parquet files (default: from config.yaml)",
    )
    
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="API endpoint for live mode (default: from config.yaml)",
    )
    
    parser.add_argument(
        "--kafka-broker",
        type=str,
        default="kafka:9092",
        help="Kafka bootstrap servers for kafka mode (default: kafka:9092)",
    )
    
    parser.add_argument(
        "--kafka-topic",
        type=str,
        default="events",
        help="Kafka topic name for kafka mode (default: events)",
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for kafka mode (default: 100)",
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    return parser.parse_args()


def run_replay_mode(generator: BehaviorGenerator, args: argparse.Namespace):
    """Run simulator in replay mode (write Parquet files)."""
    print(f"\n{'=' * 70}")
    print(f"🎬 REPLAY MODE - Generating Synthetic Events")
    print(f"{'=' * 70}")
    print(f"Events:         {args.events:,}")
    print(f"Users:          {args.users or generator.config['simulation']['num_users']:,}")
    print(f"Random Seed:    {generator.config['simulation']['random_seed']}")
    print(f"Output Dir:     {args.output_dir or generator.config['output']['parquet_dir']}")
    print(f"{'=' * 70}\n")
    
    # Generate events with progress bar
    print("📊 Generating events...")
    start_time = time.time()
    
    events = generator.generate_events(
        num_events=args.events,
        num_users=args.users,
    )
    
    generation_time = time.time() - start_time
    print(f"✅ Generated {len(events):,} events in {generation_time:.2f}s")
    print(f"   ({len(events) / generation_time:.0f} events/sec)\n")
    
    # Save to Parquet
    print("💾 Saving to Parquet files...")
    save_start = time.time()
    
    generator.save_to_parquet(
        events=events,
        output_dir=args.output_dir,
    )
    
    save_time = time.time() - save_start
    print(f"✅ Saved in {save_time:.2f}s\n")
    
    # Statistics
    print(f"{'=' * 70}")
    print(f"📈 STATISTICS")
    print(f"{'=' * 70}")
    
    # Event type distribution
    event_types = {}
    for event in events:
        event_types[event.event_type] = event_types.get(event.event_type, 0) + 1
    
    print("\nEvent Type Distribution:")
    for event_type, count in sorted(event_types.items()):
        percentage = (count / len(events)) * 100
        bar = "█" * int(percentage / 2)
        print(f"  {event_type:15s} {count:6,} ({percentage:5.1f}%) {bar}")
    
    # User distribution
    unique_users = len(set(event.user_id for event in events))
    print(f"\nUnique Users:     {unique_users:,}")
    print(f"Unique Sessions:  {len(set(event.session_id for event in events)):,}")
    print(f"Avg Events/User:  {len(events) / unique_users:.1f}")
    
    total_time = time.time() - start_time
    print(f"\n⏱️  Total Time:      {total_time:.2f}s")
    print(f"{'=' * 70}\n")


def run_live_mode(generator: BehaviorGenerator, args: argparse.Namespace):
    """Run simulator in live mode (send to API)."""
    rate = args.rate or generator.config["simulation"]["event_rate"]
    endpoint = args.endpoint or generator.config["output"]["api_endpoint"]
    
    print(f"\n{'=' * 70}")
    print(f"🚀 LIVE MODE - Sending Events to API")
    print(f"{'=' * 70}")
    print(f"Events:         {args.events:,}")
    print(f"Users:          {args.users or generator.config['simulation']['num_users']:,}")
    print(f"Rate:           {rate} events/sec")
    print(f"Endpoint:       {endpoint}")
    print(f"Random Seed:    {generator.config['simulation']['random_seed']}")
    print(f"{'=' * 70}\n")
    
    # Generate events
    print("📊 Generating events...")
    start_time = time.time()
    
    events = generator.generate_events(
        num_events=args.events,
        num_users=args.users,
    )
    
    generation_time = time.time() - start_time
    print(f"✅ Generated {len(events):,} events in {generation_time:.2f}s\n")
    
    # Send to API with progress bar
    print("🌐 Sending to API...")
    send_start = time.time()
    
    # Override endpoint if provided
    if args.endpoint:
        generator.config["output"]["api_endpoint"] = args.endpoint
    
    # Wrapper with progress bar
    stats = {"success": 0, "failed": 0}
    delay_between_events = 1.0 / rate if rate > 0 else 0
    
    with tqdm(total=len(events), unit="event", ncols=100) as pbar:
        import httpx
        with httpx.Client(timeout=30.0) as client:
            for i, event in enumerate(events):
                success = False
                retry_attempts = generator.config["output"]["retry_attempts"]
                retry_delay = generator.config["output"]["retry_delay"]
                
                for attempt in range(retry_attempts):
                    try:
                        response = client.post(
                            endpoint,
                            json=event.to_api_dict(),
                        )
                        response.raise_for_status()
                        stats["success"] += 1
                        success = True
                        break
                    except Exception as e:
                        if attempt == retry_attempts - 1:
                            stats["failed"] += 1
                            if args.verbose:
                                tqdm.write(f"❌ Failed: {e}")
                        else:
                            time.sleep(retry_delay)
                
                pbar.update(1)
                pbar.set_postfix(
                    success=stats["success"],
                    failed=stats["failed"],
                    rate=f"{rate}/s"
                )
                
                # Rate limiting
                if delay_between_events > 0 and i < len(events) - 1:
                    time.sleep(delay_between_events)
    
    send_time = time.time() - send_start
    print(f"\n✅ Completed in {send_time:.2f}s")
    
    # Statistics
    print(f"\n{'=' * 70}")
    print(f"📈 STATISTICS")
    print(f"{'=' * 70}")
    print(f"Total Events:     {len(events):,}")
    print(f"Successful:       {stats['success']:,} ({stats['success']/len(events)*100:.1f}%)")
    print(f"Failed:           {stats['failed']:,} ({stats['failed']/len(events)*100:.1f}%)")
    print(f"Actual Rate:      {len(events) / send_time:.1f} events/sec")
    
    total_time = time.time() - start_time
    print(f"\n⏱️  Total Time:      {total_time:.2f}s")
    print(f"{'=' * 70}\n")


def run_kafka_mode(generator: BehaviorGenerator, args: argparse.Namespace):
    """Run simulator in kafka mode (publish to Kafka)."""
    import asyncio
    
    print(f"\n{'=' * 70}")
    print(f"📨 KAFKA MODE - Publishing Events to Kafka")
    print(f"{'=' * 70}")
    print(f"Events:         {args.events:,}")
    print(f"Users:          {args.users or generator.config['simulation']['num_users']:,}")
    print(f"Kafka Broker:   {args.kafka_broker}")
    print(f"Kafka Topic:    {args.kafka_topic}")
    print(f"Batch Size:     {args.batch_size}")
    print(f"Random Seed:    {generator.config['simulation']['random_seed']}")
    print(f"{'=' * 70}\n")
    
    # Generate events
    print("📊 Generating events...")
    start_time = time.time()
    
    events = generator.generate_events(
        num_events=args.events,
        num_users=args.users,
    )
    
    generation_time = time.time() - start_time
    print(f"✅ Generated {len(events):,} events in {generation_time:.2f}s\n")
    
    # Send to Kafka with progress bar
    print("📨 Publishing to Kafka...")
    send_start = time.time()
    
    async def send_async():
        return await generator.send_to_kafka(
            events=events,
            bootstrap_servers=args.kafka_broker,
            topic=args.kafka_topic,
            batch_size=args.batch_size,
        )
    
    # Run async function
    stats = asyncio.run(send_async())
    
    send_time = time.time() - send_start
    print(f"\n✅ Completed in {send_time:.2f}s")
    
    # Statistics
    print(f"\n{'=' * 70}")
    print(f"📈 STATISTICS")
    print(f"{'=' * 70}")
    print(f"Total Events:     {len(events):,}")
    print(f"Successful:       {stats['success']:,} ({stats['success']/len(events)*100:.1f}%)")
    print(f"Failed:           {stats['failed']:,} ({stats['failed']/len(events)*100:.1f}%)")
    print(f"Throughput:       {len(events) / send_time:.1f} events/sec")
    
    total_time = time.time() - start_time
    print(f"\n⏱️  Total Time:      {total_time:.2f}s")
    print(f"{'=' * 70}\n")


def main():
    """Main entry point."""
    args = parse_args()
    
    # Check config file exists
    if not Path(args.config).exists():
        print(f"❌ Error: Configuration file '{args.config}' not found")
        print(f"   Please create a config.yaml file or specify --config <path>")
        sys.exit(1)
    
    try:
        # Initialize generator
        print(f"🔧 Loading configuration from {args.config}...")
        generator = BehaviorGenerator(config_path=args.config)
        
        # Override config with CLI arguments
        if args.seed is not None:
            generator.config["simulation"]["random_seed"] = args.seed
            import random
            import numpy as np
            random.seed(args.seed)
            np.random.seed(args.seed)
        
        if args.verbose:
            import logging
            logging.getLogger().setLevel(logging.DEBUG)
        
        print(f"✅ Loaded configuration")
        print(f"   Products: {len(generator.products)}")
        print(f"   Personas: {len(generator.personas)}")
        
        # Run simulation
        if args.mode == "replay":
            run_replay_mode(generator, args)
        elif args.mode == "live":
            run_live_mode(generator, args)
        elif args.mode == "kafka":
            run_kafka_mode(generator, args)
        
        print("✅ Simulation completed successfully!\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

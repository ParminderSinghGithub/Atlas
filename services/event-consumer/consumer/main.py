import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from aiokafka import AIOKafkaConsumer
from sqlalchemy import create_engine, text
import pandas as pd


# Environment variables
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
POSTGRES_URI = os.getenv("POSTGRES_URI", "postgresql://postgres:postgres@db:5432/ecommerce")
PARQUET_DIR = os.getenv("PARQUET_DIR", "/data/events_parquet")
KAFKA_TOPIC = "user_events"
GROUP_ID = "events-consumer-group"


def init_database():
    """Initialize database connection and create events table if not exists."""
    engine = create_engine(POSTGRES_URI)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                event_id VARCHAR(255) PRIMARY KEY,
                event_type VARCHAR(50),
                user_id VARCHAR(255),
                session_id VARCHAR(255),
                product_id VARCHAR(255),
                properties JSONB,
                ts TIMESTAMPTZ
            )
        """))
        conn.commit()
    print("✅ Database initialized")
    return engine


def write_event_to_postgres(engine, event_data):
    """Write event to Postgres with idempotency using ON CONFLICT DO NOTHING."""
    try:
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO events (event_id, event_type, user_id, session_id, product_id, properties, ts)
                    VALUES (:event_id, :event_type, :user_id, :session_id, :product_id, :properties, :ts)
                    ON CONFLICT (event_id) DO NOTHING
                """),
                {
                    "event_id": event_data.get("event_id"),
                    "event_type": event_data.get("event_type"),
                    "user_id": event_data.get("user_id"),
                    "session_id": event_data.get("session_id"),
                    "product_id": event_data.get("product_id"),
                    "properties": json.dumps(event_data.get("properties", {})),
                    "ts": event_data.get("timestamp"),
                }
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"❌ Failed to write to Postgres: {e}")
        return False


def write_event_to_parquet(event_data):
    """Write event to Parquet file partitioned by date."""
    try:
        # Parse timestamp to get date for partitioning
        timestamp = event_data.get("ts")
        if timestamp:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
        else:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Create partition directory
        partition_dir = Path(PARQUET_DIR) / f"date={date_str}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Filename based on event_id
        event_id = event_data.get("event_id")
        parquet_file = partition_dir / f"{event_id}.parquet"
        
        # Convert event to DataFrame and write as Parquet
        df = pd.DataFrame([event_data])
        df.to_parquet(parquet_file, engine="pyarrow", index=False)
        
        return True
    except Exception as e:
        print(f"❌ Failed to write to Parquet: {e}")
        return False


async def consume_events():
    """Main consumer loop - consume from Kafka and write to Postgres + Parquet."""
    print(f"🚀 Starting Event Consumer")
    print(f"   Kafka Broker: {KAFKA_BROKER}")
    print(f"   Topic: {KAFKA_TOPIC}")
    print(f"   Group ID: {GROUP_ID}")
    print(f"   Postgres: {POSTGRES_URI}")
    print(f"   Parquet Dir: {PARQUET_DIR}")
    
    # Initialize database
    engine = init_database()
    
    # Create Kafka consumer
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    
    await consumer.start()
    print(f"✅ Consumer started, listening for messages...")
    
    try:
        async for msg in consumer:
            event_data = msg.value
            event_id = event_data.get("event_id", "unknown")
            event_type = event_data.get("event_type", "unknown")
            
            print(f"📨 Received event: {event_id} (type: {event_type})")
            
            # Write to Postgres
            pg_success = write_event_to_postgres(engine, event_data)
            if pg_success:
                print(f"   ✅ Written to Postgres")
            
            # Write to Parquet
            parquet_success = write_event_to_parquet(event_data)
            if parquet_success:
                print(f"   ✅ Written to Parquet")
            
    except Exception as e:
        print(f"❌ Consumer error: {e}")
    finally:
        await consumer.stop()
        engine.dispose()
        print("🛑 Consumer stopped")


if __name__ == "__main__":
    print("=" * 50)
    print("EVENT CONSUMER STARTING...")
    print("=" * 50)
    try:
        asyncio.run(consume_events())
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

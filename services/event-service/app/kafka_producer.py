import asyncio
from aiokafka import AIOKafkaProducer
from typing import Optional

_producer: Optional[AIOKafkaProducer] = None
_lock = asyncio.Lock()


async def get_producer() -> AIOKafkaProducer:
    """Singleton lazy-initialized Kafka producer."""
    global _producer
    if _producer is None:
        async with _lock:
            if _producer is None:
                _producer = AIOKafkaProducer(
                    bootstrap_servers="kafka:9092",
                    compression_type="gzip",
                    acks="all",
                    enable_idempotence=True,
                )
                await _producer.start()
    return _producer


async def close_producer():
    """Close the Kafka producer on shutdown."""
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None

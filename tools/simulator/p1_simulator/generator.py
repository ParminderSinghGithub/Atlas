"""
Synthetic User Behavior Generator for P1 E-commerce Platform

This module generates realistic user behavior events including views, clicks,
add-to-cart actions, and purchases based on configurable personas and Markov chains.
"""

import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging

import httpx
import numpy as np
import pandas as pd
import yaml

try:
    from aiokafka import AIOKafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    AIOKafkaProducer = None


logger = logging.getLogger(__name__)


class EventModel:
    """Event model matching the P1 event schema."""
    
    def __init__(
        self,
        event_type: str,
        user_id: str,
        session_id: str,
        product_id: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.event_id = str(uuid.uuid4())
        self.event_type = event_type
        self.user_id = user_id
        self.session_id = session_id
        self.product_id = product_id
        self.properties = properties or {}
        self.ts = (timestamp or datetime.now(timezone.utc)).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "product_id": self.product_id,
            "properties": self.properties,
            "ts": self.ts,
        }
    
    def to_api_dict(self) -> Dict[str, Any]:
        """Convert event to API payload (without event_id and ts - server generates)."""
        return {
            "event_type": self.event_type,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "product_id": self.product_id,
            "properties": self.properties,
        }
    
    def to_kafka_dict(self) -> Dict[str, Any]:
        """Convert event to Kafka message payload."""
        return self.to_dict()
    
    def get_kafka_key(self) -> str:
        """Generate Kafka partition key from user_id and session_id."""
        return f"{self.user_id}|{self.session_id}"


class ProductLoader:
    """Load products from file or API."""
    
    @staticmethod
    def load_from_file(file_path: str) -> List[Dict]:
        """Load products from JSON file."""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Product file {file_path} not found, using sample data")
            return ProductLoader._get_sample_products()
        
        with open(path, 'r') as f:
            products = json.load(f)
        
        logger.info(f"Loaded {len(products)} products from {file_path}")
        return products
    
    @staticmethod
    def load_from_api(api_url: str) -> List[Dict]:
        """Load products from API endpoint."""
        try:
            response = httpx.get(api_url, timeout=10.0)
            response.raise_for_status()
            products = response.json()
            
            # Normalize API response (handle different formats)
            if isinstance(products, dict) and "data" in products:
                products = products["data"]
            
            logger.info(f"Loaded {len(products)} products from API")
            return products
        
        except Exception as e:
            logger.error(f"Failed to load products from API: {e}")
            logger.info("Falling back to sample products")
            return ProductLoader._get_sample_products()
    
    @staticmethod
    def _get_sample_products() -> List[Dict]:
        """Generate sample products for testing."""
        return [
            {"id": "1", "name": "iPhone 15 Pro", "price": 999.99, "category": "electronics"},
            {"id": "2", "name": "MacBook Pro M3", "price": 1999.99, "category": "computers"},
            {"id": "3", "name": "AirPods Pro", "price": 249.99, "category": "accessories"},
            {"id": "4", "name": "iPad Air", "price": 599.99, "category": "electronics"},
            {"id": "5", "name": "Apple Watch", "price": 399.99, "category": "accessories"},
        ]


class UserPersona:
    """User persona with category preferences."""
    
    def __init__(self, name: str, category_weights: Dict[str, float]):
        self.name = name
        self.category_weights = category_weights
        self.categories = list(category_weights.keys())
        self.weights = list(category_weights.values())
    
    def select_product(self, products: List[Dict]) -> Dict:
        """Select a product based on persona preferences."""
        # Group products by category
        products_by_category = {}
        for product in products:
            category = product.get("category", "other")
            if category not in products_by_category:
                products_by_category[category] = []
            products_by_category[category].append(product)
        
        # Select category based on weights
        available_categories = [c for c in self.categories if c in products_by_category]
        if not available_categories:
            # Fallback to random product
            return random.choice(products)
        
        available_weights = [
            self.category_weights[c] for c in available_categories
        ]
        # Normalize weights
        total = sum(available_weights)
        normalized_weights = [w / total for w in available_weights]
        
        selected_category = np.random.choice(available_categories, p=normalized_weights)
        return random.choice(products_by_category[selected_category])


class MarkovChain:
    """Markov chain for action transitions."""
    
    def __init__(self, transitions: Dict[str, Dict[str, float]]):
        self.transitions = transitions
        self.states = list(transitions.keys())
    
    def next_action(self, current_action: str) -> Optional[str]:
        """Determine next action based on current state."""
        if current_action not in self.transitions:
            return None
        
        next_states = list(self.transitions[current_action].keys())
        probabilities = list(self.transitions[current_action].values())
        
        # Normalize probabilities
        total = sum(probabilities)
        if total == 0:
            return None
        
        normalized_probs = [p / total for p in probabilities]
        next_state = np.random.choice(next_states, p=normalized_probs)
        
        return next_state if next_state != "exit" else None


class SessionSimulator:
    """Simulate a user session with multiple events."""
    
    def __init__(
        self,
        user_id: str,
        persona: UserPersona,
        products: List[Dict],
        markov_chain: MarkovChain,
        config: Dict,
    ):
        self.user_id = user_id
        self.session_id = str(uuid.uuid4())
        self.persona = persona
        self.products = products
        self.markov_chain = markov_chain
        self.config = config
        self.session_start = datetime.now(timezone.utc)
        self.current_time = self.session_start
        self.cart_items = []
    
    def generate_session(self) -> List[EventModel]:
        """Generate a complete user session."""
        events = []
        current_action = "view"  # Always start with a view
        session_duration = random.uniform(
            self.config["session"]["min_duration_seconds"],
            self.config["session"]["max_duration_seconds"],
        )
        session_end = self.session_start + timedelta(seconds=session_duration)
        
        while self.current_time < session_end and current_action:
            # Generate event
            event = self._generate_event(current_action)
            if event:
                events.append(event)
            
            # Advance time
            time_delta = max(
                1,
                np.random.normal(
                    self.config["session"]["avg_time_between_actions"],
                    self.config["session"]["time_variance"],
                ),
            )
            self.current_time += timedelta(seconds=time_delta)
            
            # Determine next action
            current_action = self.markov_chain.next_action(current_action)
        
        logger.debug(
            f"Generated session {self.session_id} for user {self.user_id}: "
            f"{len(events)} events over {session_duration:.0f}s"
        )
        return events
    
    def _generate_event(self, event_type: str) -> Optional[EventModel]:
        """Generate a single event."""
        if event_type == "exit":
            return None
        
        # Select product (except for purchase, which uses cart)
        if event_type == "purchase" and self.cart_items:
            product = random.choice(self.cart_items)
        else:
            product = self.persona.select_product(self.products)
        
        # Add to cart tracking
        if event_type == "add_to_cart":
            self.cart_items.append(product)
        elif event_type == "purchase" and product in self.cart_items:
            self.cart_items.remove(product)
        
        # Generate event properties
        properties = self._generate_properties(event_type, product)
        
        event = EventModel(
            event_type=event_type,
            user_id=self.user_id,
            session_id=self.session_id,
            product_id=str(product.get("id", product.get("ID", "unknown"))),
            properties=properties,
            timestamp=self.current_time,
        )
        
        return event
    
    def _generate_properties(self, event_type: str, product: Dict) -> Dict[str, Any]:
        """Generate event-specific properties."""
        base_properties = {}
        
        if event_type not in self.config["event_properties"]:
            return base_properties
        
        for prop_config in self.config["event_properties"][event_type]:
            for key, values in prop_config.items():
                base_properties[key] = random.choice(values)
        
        # Add product-specific properties
        if event_type == "add_to_cart":
            base_properties["price"] = product.get("price", 0.0)
        elif event_type == "purchase":
            base_properties["total"] = product.get("price", 0.0) * base_properties.get(
                "quantity", 1
            )
        
        return base_properties


class BehaviorGenerator:
    """Main behavior generator orchestrating the simulation."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.products = self._load_products()
        self.personas = self._create_personas()
        self.markov_chain = self._create_markov_chain()
        self._setup_logging()
        
        # Set random seed for reproducibility
        random.seed(self.config["simulation"]["random_seed"])
        np.random.seed(self.config["simulation"]["random_seed"])
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    
    def _load_products(self) -> List[Dict]:
        """Load products based on configuration."""
        source = self.config["products"]["source"]
        
        if source == "file":
            return ProductLoader.load_from_file(self.config["products"]["file_path"])
        elif source == "api":
            return ProductLoader.load_from_api(self.config["products"]["api_url"])
        else:
            logger.warning(f"Unknown product source: {source}, using sample data")
            return ProductLoader._get_sample_products()
    
    def _create_personas(self) -> List[Tuple[UserPersona, float]]:
        """Create user personas with probabilities."""
        personas = []
        for persona_config in self.config["personas"]:
            persona = UserPersona(
                name=persona_config["name"],
                category_weights=persona_config["category_weights"],
            )
            probability = persona_config["probability"]
            personas.append((persona, probability))
        
        return personas
    
    def _create_markov_chain(self) -> MarkovChain:
        """Create Markov chain from configuration."""
        return MarkovChain(self.config["transitions"])
    
    def _setup_logging(self):
        """Setup logging configuration."""
        level = getattr(logging, self.config["logging"]["level"])
        logging.basicConfig(
            level=level,
            format=self.config["logging"]["format"],
        )
    
    def generate_events(self, num_events: int, num_users: Optional[int] = None) -> List[EventModel]:
        """Generate events across multiple users and sessions."""
        if num_users is None:
            num_users = self.config["simulation"]["num_users"]
        
        all_events = []
        events_generated = 0
        
        logger.info(f"Generating {num_events} events for {num_users} users")
        
        while events_generated < num_events:
            # Select user
            user_id = f"user_{random.randint(1, num_users):05d}"
            
            # Select persona
            personas_list = [p[0] for p in self.personas]
            probabilities = [p[1] for p in self.personas]
            persona = np.random.choice(personas_list, p=probabilities)
            
            # Generate session
            simulator = SessionSimulator(
                user_id=user_id,
                persona=persona,
                products=self.products,
                markov_chain=self.markov_chain,
                config=self.config,
            )
            
            session_events = simulator.generate_session()
            all_events.extend(session_events)
            events_generated += len(session_events)
        
        # Trim to exact number requested
        all_events = all_events[:num_events]
        
        logger.info(f"Generated {len(all_events)} events")
        return all_events
    
    def events_to_dataframe(self, events: List[EventModel]) -> pd.DataFrame:
        """Convert events to pandas DataFrame."""
        data = [event.to_dict() for event in events]
        df = pd.DataFrame(data)
        
        # Convert timestamp to datetime
        df['ts'] = pd.to_datetime(df['ts'])
        
        return df
    
    def save_to_parquet(self, events: List[EventModel], output_dir: Optional[str] = None):
        """Save events to Parquet files partitioned by date."""
        if output_dir is None:
            output_dir = self.config["output"]["parquet_dir"]
        
        df = self.events_to_dataframe(events)
        
        if self.config["output"]["partition_by_date"]:
            # Partition by date
            df['date'] = df['ts'].dt.date
            
            for date, group in df.groupby('date'):
                partition_dir = Path(output_dir) / f"date={date}"
                partition_dir.mkdir(parents=True, exist_ok=True)
                
                # Drop the date column for storage
                group_data = group.drop(columns=['date'])
                
                # Save with timestamp in filename for uniqueness
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = partition_dir / f"synthetic_events_{timestamp}.parquet"
                
                group_data.to_parquet(filename, engine="pyarrow", index=False)
                logger.info(f"Saved {len(group_data)} events to {filename}")
        else:
            # Save all events to single file
            output_path = Path(output_dir) / "synthetic_events.parquet"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            df.to_parquet(output_path, engine="pyarrow", index=False)
            logger.info(f"Saved {len(df)} events to {output_path}")
    
    def send_to_api(
        self,
        events: List[EventModel],
        rate: Optional[float] = None,
    ) -> Dict[str, int]:
        """Send events to API endpoint at configured rate."""
        if rate is None:
            rate = self.config["simulation"]["event_rate"]
        
        endpoint = self.config["output"]["api_endpoint"]
        batch_size = self.config["output"]["batch_size"]
        retry_attempts = self.config["output"]["retry_attempts"]
        retry_delay = self.config["output"]["retry_delay"]
        
        stats = {"success": 0, "failed": 0}
        delay_between_events = 1.0 / rate if rate > 0 else 0
        
        logger.info(f"Sending {len(events)} events to {endpoint} at {rate} events/sec")
        
        with httpx.Client(timeout=30.0) as client:
            for i, event in enumerate(events):
                success = False
                
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
                        logger.warning(
                            f"Attempt {attempt + 1}/{retry_attempts} failed: {e}"
                        )
                        if attempt < retry_attempts - 1:
                            import time
                            time.sleep(retry_delay)
                
                if not success:
                    stats["failed"] += 1
                    logger.error(f"Failed to send event {event.event_id} after retries")
                
                # Rate limiting
                if delay_between_events > 0 and i < len(events) - 1:
                    import time
                    time.sleep(delay_between_events)
                
                # Progress logging
                if (i + 1) % 100 == 0:
                    logger.info(
                        f"Progress: {i + 1}/{len(events)} "
                        f"(success: {stats['success']}, failed: {stats['failed']})"
                    )
        
        logger.info(
            f"Completed: {stats['success']} succeeded, {stats['failed']} failed"
        )
        return stats
    
    async def send_to_kafka(
        self,
        events: List[EventModel],
        bootstrap_servers: str = "kafka:9092",
        topic: str = "events",
        batch_size: int = 100,
    ) -> Dict[str, int]:
        """Send events to Kafka topic using aiokafka.
        
        Args:
            events: List of events to send
            bootstrap_servers: Kafka bootstrap servers (default: kafka:9092)
            topic: Kafka topic name (default: events)
            batch_size: Number of events to batch before sending (default: 100)
        
        Returns:
            Dictionary with success and failed counts
        """
        if not KAFKA_AVAILABLE:
            raise ImportError(
                "aiokafka is not installed. Install with: pip install aiokafka"
            )
        
        stats = {"success": 0, "failed": 0}
        
        logger.info(
            f"Sending {len(events)} events to Kafka topic '{topic}' at {bootstrap_servers}"
        )
        
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            compression_type='gzip',
            acks='all',
            linger_ms=10,  # Small delay to batch messages
            max_batch_size=16384,  # 16KB batch size
        )
        
        try:
            await producer.start()
            logger.info("Kafka producer connected")
            
            # Send events in batches
            for i in range(0, len(events), batch_size):
                batch = events[i:i + batch_size]
                
                # Send batch
                for event in batch:
                    try:
                        kafka_key = event.get_kafka_key()
                        kafka_value = event.to_kafka_dict()
                        
                        # Send and await
                        await producer.send(
                            topic,
                            value=kafka_value,
                            key=kafka_key,
                        )
                        stats["success"] += 1
                    
                    except Exception as e:
                        stats["failed"] += 1
                        logger.error(f"Failed to send event {event.event_id}: {e}")
                
                # Flush batch
                await producer.flush()
                
                # Progress logging
                if (i + batch_size) % 1000 == 0 or (i + batch_size) >= len(events):
                    logger.info(
                        f"Progress: {min(i + batch_size, len(events))}/{len(events)} "
                        f"(success: {stats['success']}, failed: {stats['failed']})"
                    )
        
        finally:
            await producer.stop()
            logger.info("Kafka producer disconnected")
        
        logger.info(
            f"Completed: {stats['success']} succeeded, {stats['failed']} failed"
        )
        return stats

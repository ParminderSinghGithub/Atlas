"""Test event schema validation and serialization."""
import json
import uuid
from datetime import datetime
import pytest
from p1_simulator.generator import EventModel, ProductLoader


class TestEventModel:
    """Test EventModel schema and serialization methods."""
    
    def test_event_model_to_dict(self):
        """Test that to_dict() includes all required fields."""
        event = EventModel(
            event_type="view",
            user_id="user_00001",
            session_id=str(uuid.uuid4()),
            product_id="1",
            properties={"category": "electronics", "price": 999.99, "page": "product"}
        )
        
        event_dict = event.to_dict()
        
        # Verify all required fields present
        assert "event_id" in event_dict
        assert "event_type" in event_dict
        assert "user_id" in event_dict
        assert "session_id" in event_dict
        assert "product_id" in event_dict
        assert "ts" in event_dict
        assert "properties" in event_dict
        
        # Verify field types
        assert isinstance(event_dict["event_id"], str)
        assert isinstance(event_dict["event_type"], str)
        assert isinstance(event_dict["user_id"], str)
        assert isinstance(event_dict["session_id"], str)
        assert isinstance(event_dict["ts"], str)
        assert isinstance(event_dict["properties"], dict)
    
    def test_event_model_to_api_dict(self):
        """Test that to_api_dict() excludes event_id."""
        event = EventModel(
            event_type="click",
            user_id="user_00002",
            session_id=str(uuid.uuid4()),
            product_id="2",
            properties={"category": "computers", "price": 1499.99, "page": "product"}
        )
        
        api_dict = event.to_api_dict()
        
        # Verify event_id is excluded (API generates it)
        assert "event_id" not in api_dict
        
        # Verify other required fields present
        assert "event_type" in api_dict
        assert "user_id" in api_dict
        assert "session_id" in api_dict
        assert "product_id" in api_dict
        assert "properties" in api_dict
    
    def test_event_model_to_kafka_dict(self):
        """Test that to_kafka_dict() returns dict with all fields."""
        properties = {"category": "accessories", "price": 29.99, "page": "cart"}
        event = EventModel(
            event_type="add_to_cart",
            user_id="user_00003",
            session_id=str(uuid.uuid4()),
            product_id="3",
            properties=properties
        )
        
        kafka_dict = event.to_kafka_dict()
        
        # Verify all fields present
        assert "event_id" in kafka_dict
        assert "event_type" in kafka_dict
        assert kafka_dict["event_type"] == "add_to_cart"
        assert "properties" in kafka_dict
        assert isinstance(kafka_dict["properties"], dict)
        assert kafka_dict["properties"] == properties
    
    def test_event_model_get_kafka_key(self):
        """Test that get_kafka_key() returns user_id|session_id format."""
        user_id = "user_12345"
        session_id = "session_abcdef"
        event = EventModel(
            event_type="purchase",
            user_id=user_id,
            session_id=session_id,
            product_id="4",
            properties={"category": "electronics", "price": 799.99, "page": "checkout"}
        )
        
        kafka_key = event.get_kafka_key()
        
        # Verify format: user_id|session_id
        assert kafka_key == f"{user_id}|{session_id}"
        assert "|" in kafka_key
        parts = kafka_key.split("|")
        assert len(parts) == 2
        assert parts[0] == user_id
        assert parts[1] == session_id
    
    def test_event_types_valid(self):
        """Test that all event types are valid."""
        valid_event_types = ["view", "click", "add_to_cart", "purchase"]
        
        for event_type in valid_event_types:
            event = EventModel(
                event_type=event_type,
                user_id="user_00001",
                session_id=str(uuid.uuid4()),
                product_id="1",
                properties={"category": "electronics", "price": 999.99, "page": "product"}
            )
            assert event.event_type == event_type
    
    def test_properties_structure(self):
        """Test that properties dict contains expected fields."""
        event = EventModel(
            event_type="view",
            user_id="user_00001",
            session_id=str(uuid.uuid4()),
            product_id="1",
            properties={"category": "electronics", "price": 999.99, "page": "product"}
        )
        
        # Verify properties has expected structure
        assert "category" in event.properties
        assert "price" in event.properties
        assert "page" in event.properties
        
        # Verify types
        assert isinstance(event.properties["category"], str)
        assert isinstance(event.properties["price"], (int, float))
        assert isinstance(event.properties["page"], str)
    
    def test_event_id_auto_generated(self):
        """Test that event_id is automatically generated as UUID."""
        event = EventModel(
            event_type="view",
            user_id="user_00001",
            session_id=str(uuid.uuid4()),
            product_id="1",
            properties={}
        )
        
        # Should have event_id
        assert hasattr(event, 'event_id')
        assert event.event_id is not None
        
        # Should be valid UUID
        uuid.UUID(event.event_id)
    
    def test_timestamp_auto_generated(self):
        """Test that timestamp is automatically generated."""
        event = EventModel(
            event_type="view",
            user_id="user_00001",
            session_id=str(uuid.uuid4()),
            product_id="1",
            properties={}
        )
        
        # Should have ts
        assert hasattr(event, 'ts')
        assert event.ts is not None
        
        # Should be valid ISO 8601
        datetime.fromisoformat(event.ts)


class TestProductLoader:
    """Test ProductLoader handles different sources correctly."""
    
    def test_sample_products_have_valid_schema(self):
        """Test that sample products have required fields."""
        products = ProductLoader._get_sample_products()
        
        assert len(products) > 0
        
        for product in products:
            assert "id" in product
            assert "name" in product
            assert "category" in product
            assert "price" in product
            
            # Verify types (id can be string or int)
            assert isinstance(product["id"], (int, str))
            assert isinstance(product["name"], str)
            assert isinstance(product["category"], str)
            assert isinstance(product["price"], (int, float))
            
            # Verify reasonable values
            assert len(product["name"]) > 0
            assert product["category"] in ["electronics", "computers", "accessories"]
            assert product["price"] > 0

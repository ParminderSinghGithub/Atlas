"""Test reproducibility - same seed produces same event sequences."""
import pytest
import random
import numpy as np
import tempfile
import yaml
from pathlib import Path
from p1_simulator.generator import BehaviorGenerator


class TestReproducibility:
    """Test that same seed produces identical event sequences."""
    
    def create_test_config(self, seed):
        """Helper to create temporary config file with given seed."""
        config_data = {
            'simulation': {
                'random_seed': seed,
                'num_users': 10,
                'num_events_per_user': 10,
                'start_time': '2025-11-01T00:00:00',
                'end_time': '2025-11-02T00:00:00'
            },
            'personas': [
                {
                    'name': 'tech_enthusiast',
                    'probability': 0.5,
                    'category_weights': {'electronics': 0.6, 'computers': 0.3, 'accessories': 0.1}
                },
                {
                    'name': 'casual_shopper',
                    'probability': 0.5,
                    'category_weights': {'electronics': 0.3, 'computers': 0.3, 'accessories': 0.4}
                }
            ],
            'transitions': {
                'view': {'click': 0.3, 'view': 0.5, 'exit': 0.2},
                'click': {'add_to_cart': 0.35, 'view': 0.45, 'exit': 0.2},
                'add_to_cart': {'purchase': 0.35, 'view': 0.4, 'exit': 0.25},
                'purchase': {'view': 0.5, 'exit': 0.5}
            },
            'session': {
                'min_duration_seconds': 60,
                'max_duration_seconds': 600,
                'min_events_per_session': 3,
                'max_events_per_session': 15,
                'avg_time_between_actions': 30,
                'time_variance': 10
            },
            'products': {
                'source': 'sample'
            },
            'event_properties': {
                'view': [
                    {'page': ['product_detail', 'product_list']}
                ],
                'click': [
                    {'element': ['buy_button', 'add_to_cart']}
                ],
                'add_to_cart': [
                    {'quantity': [1, 2]}
                ],
                'purchase': [
                    {'payment_method': ['credit_card', 'paypal']}
                ]
            },
            'output': {
                'parquet_path': 'test_output.parquet',
                'api_endpoint': 'http://localhost:8000/events'
            },
            'logging': {
                'level': 'ERROR',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            }
        }
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        yaml.dump(config_data, temp_file)
        temp_file.close()
        return temp_file.name
    
    def test_same_seed_produces_identical_sequences(self):
        """Test that using the same seed twice produces identical event sequences."""
        seed = 42
        
        # Generate events with seed 42 (first run)
        config_path1 = self.create_test_config(seed)
        try:
            generator1 = BehaviorGenerator(config_path=config_path1)
            events1 = generator1.generate_events(num_events=30)
        finally:
            Path(config_path1).unlink(missing_ok=True)
        
        # Generate events with seed 42 (second run)
        config_path2 = self.create_test_config(seed)
        try:
            generator2 = BehaviorGenerator(config_path=config_path2)
            events2 = generator2.generate_events(num_events=30)
        finally:
            Path(config_path2).unlink(missing_ok=True)
        
        # Should produce same number of events
        assert len(events1) == len(events2)
        
        # Should produce identical event sequences (except UUIDs which are random)
        # Group events by session for comparison
        sessions1 = {}
        for e in events1:
            if e.user_id not in sessions1:
                sessions1[e.user_id] = []
            sessions1[e.user_id].append((e.event_type, e.product_id))
        
        sessions2 = {}
        for e in events2:
            if e.user_id not in sessions2:
                sessions2[e.user_id] = []
            sessions2[e.user_id].append((e.event_type, e.product_id))
        
        # Same users should appear
        assert set(sessions1.keys()) == set(sessions2.keys())
        
        # Each user's event sequence should match
        for user_id in sessions1.keys():
            assert sessions1[user_id] == sessions2[user_id], f"User {user_id}: event sequence mismatch"
    
    def test_different_seeds_produce_different_sequences(self):
        """Test that different seeds produce different event sequences."""
        # Generate with seed 42
        config_path1 = self.create_test_config(seed=42)
        try:
            generator1 = BehaviorGenerator(config_path=config_path1)
            events1 = generator1.generate_events(num_events=30)
        finally:
            Path(config_path1).unlink(missing_ok=True)
        
        # Generate with seed 123
        config_path2 = self.create_test_config(seed=123)
        try:
            generator2 = BehaviorGenerator(config_path=config_path2)
            events2 = generator2.generate_events(num_events=30)
        finally:
            Path(config_path2).unlink(missing_ok=True)
        
        # Should produce same number of events
        assert len(events1) == len(events2)
        
        # Should produce different sequences (at least some differences)
        differences = 0
        for e1, e2 in zip(events1, events2):
            if (e1.event_type != e2.event_type or 
                e1.user_id != e2.user_id or 
                e1.product_id != e2.product_id):
                differences += 1
        
        # With different seeds, we expect significant differences
        assert differences > len(events1) * 0.1, "Different seeds should produce different sequences"
    
    def test_python_random_seeding(self):
        """Test that Python's random module respects seed."""
        # Set seed and generate numbers
        random.seed(42)
        numbers1 = [random.random() for _ in range(10)]
        
        # Reset seed and generate again
        random.seed(42)
        numbers2 = [random.random() for _ in range(10)]
        
        # Should be identical
        assert numbers1 == numbers2
    
    def test_numpy_random_seeding(self):
        """Test that numpy's random respects seed."""
        # Set seed and generate numbers
        np.random.seed(42)
        numbers1 = np.random.rand(10).tolist()
        
        # Reset seed and generate again
        np.random.seed(42)
        numbers2 = np.random.rand(10).tolist()
        
        # Should be identical
        assert numbers1 == numbers2

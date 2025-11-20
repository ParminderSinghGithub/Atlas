"""Test persona-weighted product selection logic."""
import pytest
from collections import Counter
from p1_simulator.generator import UserPersona


class TestPersonaWeightedSelection:
    """Test that personas select products according to category weights."""
    
    def get_diverse_products(self):
        """Helper to create products across all categories."""
        return [
            # Electronics (10 products)
            {"id": "1", "name": "Smartphone", "category": "electronics", "price": 799.99},
            {"id": "2", "name": "Tablet", "category": "electronics", "price": 499.99},
            {"id": "3", "name": "Smartwatch", "category": "electronics", "price": 299.99},
            {"id": "4", "name": "Headphones", "category": "electronics", "price": 199.99},
            {"id": "5", "name": "Speaker", "category": "electronics", "price": 149.99},
            {"id": "6", "name": "Camera", "category": "electronics", "price": 899.99},
            {"id": "7", "name": "TV", "category": "electronics", "price": 1299.99},
            {"id": "8", "name": "Console", "category": "electronics", "price": 499.99},
            {"id": "9", "name": "E-reader", "category": "electronics", "price": 129.99},
            {"id": "10", "name": "Drone", "category": "electronics", "price": 699.99},
            
            # Computers (10 products)
            {"id": "11", "name": "Laptop", "category": "computers", "price": 1299.99},
            {"id": "12", "name": "Desktop", "category": "computers", "price": 1499.99},
            {"id": "13", "name": "Monitor", "category": "computers", "price": 399.99},
            {"id": "14", "name": "Keyboard", "category": "computers", "price": 79.99},
            {"id": "15", "name": "Mouse", "category": "computers", "price": 49.99},
            {"id": "16", "name": "Webcam", "category": "computers", "price": 89.99},
            {"id": "17", "name": "Router", "category": "computers", "price": 129.99},
            {"id": "18", "name": "Hard Drive", "category": "computers", "price": 119.99},
            {"id": "19", "name": "SSD", "category": "computers", "price": 159.99},
            {"id": "20", "name": "RAM", "category": "computers", "price": 99.99},
            
            # Accessories (10 products)
            {"id": "21", "name": "USB Cable", "category": "accessories", "price": 9.99},
            {"id": "22", "name": "Phone Case", "category": "accessories", "price": 19.99},
            {"id": "23", "name": "Screen Protector", "category": "accessories", "price": 14.99},
            {"id": "24", "name": "Charger", "category": "accessories", "price": 24.99},
            {"id": "25", "name": "Adapter", "category": "accessories", "price": 29.99},
            {"id": "26", "name": "Stand", "category": "accessories", "price": 39.99},
            {"id": "27", "name": "Bag", "category": "accessories", "price": 49.99},
            {"id": "28", "name": "Stylus", "category": "accessories", "price": 34.99},
            {"id": "29", "name": "Earbuds", "category": "accessories", "price": 59.99},
            {"id": "30", "name": "Power Bank", "category": "accessories", "price": 44.99},
        ]
    
    def test_tech_enthusiast_prefers_electronics(self):
        """Test that tech enthusiasts select more electronics (60% weight)."""
        products = self.get_diverse_products()
        
        # Tech enthusiast: electronics=0.6, computers=0.3, accessories=0.1
        persona = UserPersona('tech_enthusiast', {
            'electronics': 0.6,
            'computers': 0.3,
            'accessories': 0.1
        })
        
        # Select products many times and track categories
        category_counts = Counter()
        num_selections = 1000
        
        for _ in range(num_selections):
            selected = persona.select_product(products)
            category_counts[selected['category']] += 1
        
        # Calculate proportions
        electronics_pct = category_counts['electronics'] / num_selections
        computers_pct = category_counts['computers'] / num_selections
        accessories_pct = category_counts['accessories'] / num_selections
        
        # Should be close to configured weights (allow 10% variance for randomness)
        assert 0.5 < electronics_pct < 0.7, f"Electronics: {electronics_pct:.2%} (expected ~60%)"
        assert 0.2 < computers_pct < 0.4, f"Computers: {computers_pct:.2%} (expected ~30%)"
        assert 0.0 < accessories_pct < 0.2, f"Accessories: {accessories_pct:.2%} (expected ~10%)"
        
        # Electronics should be most selected
        assert category_counts['electronics'] > category_counts['computers']
        assert category_counts['electronics'] > category_counts['accessories']
    
    def test_casual_shopper_balanced_selection(self):
        """Test that casual shoppers have balanced category selection."""
        products = self.get_diverse_products()
        
        # Casual shopper: electronics=0.3, computers=0.3, accessories=0.4
        persona = UserPersona('casual_shopper', {
            'electronics': 0.3,
            'computers': 0.3,
            'accessories': 0.4
        })
        
        category_counts = Counter()
        num_selections = 1000
        
        for _ in range(num_selections):
            selected = persona.select_product(products)
            category_counts[selected['category']] += 1
        
        electronics_pct = category_counts['electronics'] / num_selections
        computers_pct = category_counts['computers'] / num_selections
        accessories_pct = category_counts['accessories'] / num_selections
        
        # Should be relatively balanced with slight accessories preference
        assert 0.2 < electronics_pct < 0.4, f"Electronics: {electronics_pct:.2%} (expected ~30%)"
        assert 0.2 < computers_pct < 0.4, f"Computers: {computers_pct:.2%} (expected ~30%)"
        assert 0.3 < accessories_pct < 0.5, f"Accessories: {accessories_pct:.2%} (expected ~40%)"
        
        # Accessories should be most selected
        assert category_counts['accessories'] >= category_counts['electronics']
        assert category_counts['accessories'] >= category_counts['computers']
    
    def test_bargain_hunter_prefers_accessories(self):
        """Test that bargain hunters prefer accessories (60% weight)."""
        products = self.get_diverse_products()
        
        # Bargain hunter: electronics=0.2, computers=0.2, accessories=0.6
        persona = UserPersona('bargain_hunter', {
            'electronics': 0.2,
            'computers': 0.2,
            'accessories': 0.6
        })
        
        category_counts = Counter()
        num_selections = 1000
        
        for _ in range(num_selections):
            selected = persona.select_product(products)
            category_counts[selected['category']] += 1
        
        electronics_pct = category_counts['electronics'] / num_selections
        computers_pct = category_counts['computers'] / num_selections
        accessories_pct = category_counts['accessories'] / num_selections
        
        # Accessories should dominate
        assert 0.5 < accessories_pct < 0.7, f"Accessories: {accessories_pct:.2%} (expected ~60%)"
        assert 0.1 < electronics_pct < 0.3, f"Electronics: {electronics_pct:.2%} (expected ~20%)"
        assert 0.1 < computers_pct < 0.3, f"Computers: {computers_pct:.2%} (expected ~20%)"
        
        assert category_counts['accessories'] > category_counts['electronics']
        assert category_counts['accessories'] > category_counts['computers']
    
    def test_persona_selects_from_available_products_only(self):
        """Test that persona only selects from products in the provided list."""
        products = self.get_diverse_products()
        product_ids = {p['id'] for p in products}
        
        persona = UserPersona('tech_enthusiast', {
            'electronics': 0.6,
            'computers': 0.3,
            'accessories': 0.1
        })
        
        # Select many times
        for _ in range(100):
            selected = persona.select_product(products)
            assert selected['id'] in product_ids
            assert selected in products
    
    def test_extreme_weights_single_category(self):
        """Test persona with extreme weights (100% one category)."""
        products = self.get_diverse_products()
        
        # 100% electronics
        persona = UserPersona('test_persona', {
            'electronics': 1.0,
            'computers': 0.0,
            'accessories': 0.0
        })
        
        category_counts = Counter()
        for _ in range(100):
            selected = persona.select_product(products)
            category_counts[selected['category']] += 1
        
        # Should select only electronics
        assert category_counts['electronics'] == 100
        assert category_counts['computers'] == 0
        assert category_counts['accessories'] == 0
    
    def test_persona_weights_with_limited_products(self):
        """Test persona selection when some categories have fewer products."""
        # Only 2 electronics, many accessories
        products = [
            {"id": "1", "name": "Phone", "category": "electronics", "price": 799.99},
            {"id": "2", "name": "Tablet", "category": "electronics", "price": 499.99},
            {"id": "3", "name": "Cable 1", "category": "accessories", "price": 9.99},
            {"id": "4", "name": "Cable 2", "category": "accessories", "price": 9.99},
            {"id": "5", "name": "Cable 3", "category": "accessories", "price": 9.99},
            {"id": "6", "name": "Cable 4", "category": "accessories", "price": 9.99},
            {"id": "7", "name": "Cable 5", "category": "accessories", "price": 9.99},
            {"id": "8", "name": "Cable 6", "category": "accessories", "price": 9.99},
        ]
        
        # Tech enthusiast prefers electronics
        persona = UserPersona('tech_enthusiast', {
            'electronics': 0.8,
            'computers': 0.0,
            'accessories': 0.2
        })
        
        category_counts = Counter()
        selected_ids = Counter()
        
        for _ in range(500):
            selected = persona.select_product(products)
            category_counts[selected['category']] += 1
            selected_ids[selected['id']] += 1
        
        # Should still prefer electronics category despite fewer products
        electronics_pct = category_counts['electronics'] / 500
        assert electronics_pct > 0.6, f"Should prefer electronics even with fewer products"
        
        # Should select from both electronics products
        assert selected_ids["1"] > 0
        assert selected_ids["2"] > 0

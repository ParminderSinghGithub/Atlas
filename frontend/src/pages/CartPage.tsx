import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { eventService } from '../services/eventService';

interface CartItem {
  productId: string;
  name?: string;
  price?: number;
}

export const CartPage: React.FC = () => {
  const { userId } = useAuth();
  const [cart, setCart] = useState<CartItem[]>([]);
  const [purchasing, setPurchasing] = useState(false);
  const [showToast, setShowToast] = useState(false);

  useEffect(() => {
    loadCart();
  }, []);

  const loadCart = () => {
    const cartData = JSON.parse(localStorage.getItem('cart') || '[]');
    setCart(cartData);
  };

  const handlePurchase = async () => {
    if (!userId || cart.length === 0) return;

    setPurchasing(true);

    // Fire purchase event for each item
    for (const item of cart) {
      await eventService.trackPurchase(userId, item.productId);
    }

    // Clear cart
    localStorage.setItem('cart', '[]');
    setCart([]);
    
    setPurchasing(false);
    
    // Show toast notification
    setShowToast(true);
    setTimeout(() => setShowToast(false), 3000);
  };

  const handleRemoveItem = (index: number) => {
    const newCart = cart.filter((_, i) => i !== index);
    setCart(newCart);
    localStorage.setItem('cart', JSON.stringify(newCart));
  };

  const totalPrice = cart.reduce((sum, item) => {
    const price = typeof item.price === 'string' ? parseFloat(item.price) : (item.price || 0);
    return sum + price;
  }, 0);

  return (
    <div className="container mx-auto px-4">
      {/* Toast Notification */}
      {showToast && (
        <div className="fixed top-20 right-8 z-50 bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg flex items-center gap-2 animate-fade-in">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          Purchase successful! Thank you for your order.
        </div>
      )}

      <h1 className="text-3xl font-bold mb-6">Shopping Cart</h1>

      {cart.length === 0 ? (
        <div className="bg-gray-100 border border-gray-300 text-gray-700 px-4 py-8 rounded text-center">
          <p className="text-xl mb-4">Your cart is empty</p>
          <p className="text-sm">Add some products to get started!</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow-md p-6">
          {/* Cart Items */}
          <div className="mb-6">
            {cart.map((item, index) => (
              <div
                key={index}
                className="flex justify-between items-center py-4 border-b"
              >
                <div>
                  <h3 className="font-semibold">{item.name || item.productId}</h3>
                  <p className="text-sm text-gray-600">
                    Product ID: {item.productId}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-lg font-bold text-green-600">
                    ₹{typeof item.price === 'string' ? parseFloat(item.price).toFixed(2) : (item.price?.toFixed(2) || '0.00')}
                  </span>
                  <button
                    onClick={() => handleRemoveItem(index)}
                    className="text-red-600 hover:text-red-800"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Total and Purchase */}
          <div className="border-t pt-4">
            <div className="flex justify-between items-center mb-4">
              <span className="text-xl font-bold">Total:</span>
              <span className="text-2xl font-bold text-green-600">
                ₹{totalPrice.toFixed(2)}
              </span>
            </div>

            <button
              onClick={handlePurchase}
              disabled={purchasing}
              className="w-full bg-green-600 text-white py-3 rounded hover:bg-green-700 disabled:bg-gray-400"
            >
              {purchasing ? 'Processing Purchase...' : 'Complete Purchase'}
            </button>

            <p className="text-xs text-gray-500 mt-2 text-center">
              Note: This is a simulation. Purchase events will be tracked for ML training.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

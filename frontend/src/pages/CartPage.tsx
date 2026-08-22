import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { eventService } from '../services/eventService';
import { Toast } from '../components/ui/Toast';

interface CartItem {
  productId: string;
  name?: string;
  price?: number | string;
  quantity?: number;
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
    try {
      const cartData = JSON.parse(localStorage.getItem('cart') || '[]');
      // Group items with quantity if not already grouped
      const normalized: CartItem[] = [];
      for (const item of cartData) {
        const existing = normalized.find((i) => i.productId === item.productId);
        if (existing) {
          existing.quantity = (existing.quantity || 1) + 1;
        } else {
          normalized.push({ ...item, quantity: item.quantity || 1 });
        }
      }
      setCart(normalized);
    } catch {
      setCart([]);
    }
  };

  const updateLocalStorage = (items: CartItem[]) => {
    // Unroll back to single items for backend compatibility
    const flat: { productId: string; name?: string; price?: number | string }[] = [];
    for (const item of items) {
      for (let i = 0; i < (item.quantity || 1); i++) {
        flat.push({ productId: item.productId, name: item.name, price: item.price });
      }
    }
    localStorage.setItem('cart', JSON.stringify(flat));
    window.dispatchEvent(new Event('storage'));
  };

  const handleUpdateQuantity = (index: number, delta: number) => {
    const updated = [...cart];
    const newQty = (updated[index].quantity || 1) + delta;
    if (newQty <= 0) {
      updated.splice(index, 1);
    } else {
      updated[index].quantity = newQty;
    }
    setCart(updated);
    updateLocalStorage(updated);
  };

  const handleRemoveItem = (index: number) => {
    const updated = cart.filter((_, i) => i !== index);
    setCart(updated);
    updateLocalStorage(updated);
  };

  const handlePurchase = async () => {
    if (!userId || cart.length === 0) return;

    setPurchasing(true);
    for (const item of cart) {
      for (let i = 0; i < (item.quantity || 1); i++) {
        await eventService.trackPurchase(userId, item.productId);
      }
    }

    localStorage.setItem('cart', '[]');
    setCart([]);
    window.dispatchEvent(new Event('storage'));
    setPurchasing(false);

    setShowToast(true);
    setTimeout(() => setShowToast(false), 3000);
  };

  const subtotal = cart.reduce((sum, item) => {
    const price = typeof item.price === 'string' ? parseFloat(item.price) : item.price || 0;
    return sum + price * (item.quantity || 1);
  }, 0);

  const totalItemCount = cart.reduce((sum, item) => sum + (item.quantity || 1), 0);

  return (
    <div className="container mx-auto px-4 sm:px-6 py-6 sm:py-10 max-w-7xl">
      <Toast show={showToast} message="Order placed successfully! Thank you." type="success" />

      <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight mb-8">
        Your Shopping Cart
      </h1>

      {cart.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-3xl p-12 sm:p-16 text-center max-w-lg mx-auto shadow-sm">
          <div className="w-16 h-16 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z" />
            </svg>
          </div>
          <h2 className="text-lg font-bold text-slate-800 mb-1">Your cart is currently empty</h2>
          <p className="text-xs text-slate-500 mb-6">
            Explore our curated catalog and add products to start shopping.
          </p>
          <Link
            to="/products"
            className="px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition-all inline-block shadow-md shadow-blue-600/20"
          >
            Start Browsing Catalog
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          {/* Left Column: Cart Items List */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white rounded-3xl border border-slate-200/80 p-6 shadow-sm divide-y divide-slate-100">
              {cart.map((item, index) => {
                const itemPrice = typeof item.price === 'string' ? parseFloat(item.price) : item.price || 0;
                const formattedItemTotal = `₹${(itemPrice * (item.quantity || 1)).toFixed(2)}`;

                return (
                  <div key={item.productId} className="py-5 first:pt-0 last:pb-0 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div className="flex items-center gap-4 flex-1">
                      <div className="w-16 h-16 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-slate-400 flex-shrink-0">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                        </svg>
                      </div>
                      <div>
                        <Link
                          to={`/products/${item.productId}`}
                          className="text-sm font-semibold text-slate-800 hover:text-blue-600 transition-colors line-clamp-1"
                        >
                          {item.name || item.productId}
                        </Link>
                        <p className="text-xs text-slate-400 mt-0.5">
                          ₹{itemPrice.toFixed(2)} each
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center justify-between sm:justify-end gap-6 w-full sm:w-auto">
                      {/* Quantity Controls */}
                      <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden bg-slate-50">
                        <button
                          onClick={() => handleUpdateQuantity(index, -1)}
                          className="px-2.5 py-1 text-slate-600 hover:bg-slate-200 text-xs font-bold transition-colors"
                        >
                          -
                        </button>
                        <span className="px-3 py-1 text-xs font-semibold text-slate-800 bg-white">
                          {item.quantity || 1}
                        </span>
                        <button
                          onClick={() => handleUpdateQuantity(index, 1)}
                          className="px-2.5 py-1 text-slate-600 hover:bg-slate-200 text-xs font-bold transition-colors"
                        >
                          +
                        </button>
                      </div>

                      {/* Total for this product */}
                      <span className="text-sm font-bold text-slate-900 min-w-[70px] text-right">
                        {formattedItemTotal}
                      </span>

                      {/* Remove Button */}
                      <button
                        onClick={() => handleRemoveItem(index)}
                        className="text-slate-400 hover:text-rose-500 transition-colors p-1"
                        title="Remove item"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Column: Order Summary Card */}
          <div className="bg-white rounded-3xl border border-slate-200/80 p-6 shadow-sm space-y-5">
            <h2 className="text-base font-bold text-slate-900 tracking-tight pb-3 border-b border-slate-100">
              Order Summary
            </h2>

            <div className="space-y-3 text-xs sm:text-sm">
              <div className="flex justify-between text-slate-600">
                <span>Items ({totalItemCount})</span>
                <span className="font-semibold text-slate-800">₹{subtotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-slate-600">
                <span>Standard Delivery</span>
                <span className="font-semibold text-emerald-600">Free</span>
              </div>
              <div className="flex justify-between text-slate-600">
                <span>Estimated Taxes</span>
                <span className="font-semibold text-slate-800">₹0.00</span>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-100 flex justify-between items-baseline">
              <span className="text-sm font-bold text-slate-900">Total</span>
              <span className="text-2xl font-extrabold text-slate-900 tracking-tight">
                ₹{subtotal.toFixed(2)}
              </span>
            </div>

            <button
              onClick={handlePurchase}
              disabled={purchasing}
              className="w-full py-3.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs sm:text-sm font-semibold transition-all duration-200 shadow-md shadow-blue-600/20 disabled:bg-slate-400 flex items-center justify-center gap-2"
            >
              {purchasing ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Processing Order...
                </>
              ) : (
                'Place Order (Test Flow)'
              )}
            </button>

            <p className="text-[11px] text-slate-400 text-center leading-relaxed">
              Test purchase flow records interactions to update your personalization profile.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

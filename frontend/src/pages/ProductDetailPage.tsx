import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { catalogService } from '../services/catalogService';
import type { Product } from '../services/catalogService';
import { recommendationService } from '../services/recommendationService';
import type { Recommendation } from '../services/recommendationService';
import { eventService } from '../services/eventService';
import { sessionService } from '../services/sessionService';
import { StructuredDescription } from '../components/StructuredDescription';

export const ProductDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { userId } = useAuth();
  const [product, setProduct] = useState<Product | null>(null);
  const [similarProducts, setSimilarProducts] = useState<Recommendation[]>([]);
  const [strategyUsed, setStrategyUsed] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [addingToCart, setAddingToCart] = useState(false);
  const [showToast, setShowToast] = useState(false);

  useEffect(() => {
    if (id) {
      loadProduct();
      // Fire view event only if userId is available
      if (userId) {
        eventService.trackView(userId, id);
        // Track product view for session re-ranking
        sessionService.trackProductView(userId, id);
      }
    }
  }, [id, userId]);

  const loadProduct = async () => {
    if (!id) return;

    setLoading(true);
    try {
      // Load product details
      const productData = await catalogService.getProduct(id);
      setProduct(productData);

      // Track category view for session re-ranking (if category exists)
      if (userId && productData.category_id) {
        sessionService.trackCategoryView(userId, productData.category_id);
      }

      // Load similar products
      const recResponse = await recommendationService.getSimilarProducts(id, 5);
      setSimilarProducts(recResponse.recommendations);
      setStrategyUsed(recResponse.strategy_used);
      console.log(`[DETAIL] Similar products strategy: ${recResponse.strategy_used}`);
    } catch (error) {
      console.error('Failed to load product:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddToCart = async () => {
    if (!userId || !id) return;

    setAddingToCart(true);
    await eventService.trackAddToCart(userId, id);
    
    // Add to local cart
    const cart = JSON.parse(localStorage.getItem('cart') || '[]');
    cart.push({ productId: id, name: product?.name, price: product?.price });
    localStorage.setItem('cart', JSON.stringify(cart));
    
    setAddingToCart(false);
    
    // Show toast notification
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2000);
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="text-center">Loading product...</div>
      </div>
    );
  }

  if (!product) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="text-center text-red-600">Product not found</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 sm:px-6">
      {/* Toast Notification */}
      {showToast && (
        <div className="fixed top-20 right-4 sm:right-8 z-50 bg-green-500 text-white px-4 sm:px-6 py-2 sm:py-3 rounded-lg shadow-lg flex items-center gap-2 animate-fade-in">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 sm:h-5 sm:w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          <span className="text-sm sm:text-base">Added to cart successfully!</span>
        </div>
      )}

      {/* Product Details */}
      <div className="bg-white rounded-lg shadow-md p-4 sm:p-6 mb-6 sm:mb-8">
        <h1 className="text-2xl sm:text-3xl font-bold mb-4">{product.name}</h1>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            {product.image_url ? (
              <img
                src={product.image_url}
                alt={product.name}
                className="w-full h-auto object-contain rounded"
              />
            ) : (
              <div className="bg-gray-200 h-64 flex items-center justify-center rounded mb-4">
                <span className="text-gray-500">No image available</span>
              </div>
            )}
          </div>
          
          <div>
            <div className="mb-4">
              <span className="text-3xl font-bold text-green-600">
                ₹{typeof product.price === 'string' ? parseFloat(product.price).toFixed(2) : product.price.toFixed(2)}
              </span>
            </div>

            {product.category_name && (
              <div className="mb-4">
                <span className="text-sm text-gray-600">
                  Category: <span className="font-semibold">{product.category_name}</span>
                </span>
              </div>
            )}

            <div className="mb-6">
              <StructuredDescription description={product.description || 'No description available'} />
            </div>

            <button
              onClick={handleAddToCart}
              disabled={addingToCart}
              className="w-full bg-blue-600 text-white py-3 rounded hover:bg-blue-700 disabled:bg-gray-400"
            >
              {addingToCart ? 'Adding...' : 'Add to Cart'}
            </button>
          </div>
        </div>
      </div>

      {/* Similar Products */}
      <section className="mb-8">
        <h2 className="text-2xl font-bold mb-4">Similar Products</h2>
        
        {similarProducts.length === 0 ? (
          <div className="text-gray-600">
            No similar products available at the moment.
          </div>
        ) : (
          <>
            <div className="text-sm text-gray-500 mb-2">
              Strategy: {strategyUsed} | {similarProducts.length} items
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
              {similarProducts.map((rec) => (
                <Link
                  key={rec.product_id}
                  to={`/products/${rec.product_id}`}
                  className="border rounded p-4 hover:shadow-lg transition group"
                >
                  {rec.image_url && (
                    <img
                      src={rec.image_url}
                      alt={rec.name || rec.product_id}
                      className="w-full h-32 object-contain mb-2"
                    />
                  )}
                  <div className="text-sm font-semibold mb-2 truncate">
                    {rec.name || rec.product_id}
                  </div>
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs text-gray-600">
                      Rank: {rec.rank}
                    </div>
                    <div className="text-xs text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                      Score: {rec.score.toFixed(3)}
                    </div>
                  </div>
                  {rec.price && (
                    <div className="text-sm font-bold text-green-600 mt-2">
                      ₹{typeof rec.price === 'string' ? parseFloat(rec.price).toFixed(2) : rec.price.toFixed(2)}
                    </div>
                  )}
                </Link>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
};

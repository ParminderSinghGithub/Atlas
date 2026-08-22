import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { catalogService } from '../services/catalogService';
import type { Product } from '../services/catalogService';
import { recommendationService } from '../services/recommendationService';
import type { Recommendation } from '../services/recommendationService';
import { eventService } from '../services/eventService';
import { sessionService } from '../services/sessionService';
import { StructuredDescription } from '../components/StructuredDescription';
import { ProductCard } from '../components/ui/ProductCard';
import { Toast } from '../components/ui/Toast';

export const ProductDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { userId, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [product, setProduct] = useState<Product | null>(null);
  const [similarProducts, setSimilarProducts] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingSimilar, setLoadingSimilar] = useState(true);
  const [addingToCart, setAddingToCart] = useState(false);
  const [showToast, setShowToast] = useState(false);

  useEffect(() => {
    if (id) {
      loadProduct();
      loadSimilarProducts();
      // Fire view event only if userId is available
      if (userId) {
        eventService.trackView(userId, id);
        sessionService.trackProductView(userId, id);
      }
    }
  }, [id, userId]);

  const loadProduct = async () => {
    if (!id) return;

    setLoading(true);
    try {
      const productData = await catalogService.getProduct(id);
      setProduct(productData);

      // Track category and product view for session re-ranking
      const activeSessionId = sessionService.getSessionId(userId);
      const productMeta = productData as Product & { category_slug?: string; category?: { slug?: string } };
      const categorySlug = productMeta.category_slug || productMeta.category?.slug || productMeta.category_name || productMeta.category_id;
      if (categorySlug) {
        sessionService.trackCategoryView(activeSessionId, String(categorySlug));
      }
      if (id) {
        sessionService.trackProductView(activeSessionId, id);
      }
    } catch (error) {
      console.error('Failed to load product:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadSimilarProducts = async () => {
    if (!id) return;
    setLoadingSimilar(true);
    try {
      const recResponse = await recommendationService.getSimilarProducts(id, 5);
      setSimilarProducts(recResponse.recommendations || []);
    } catch (error) {
      console.error('Failed to load similar products:', error);
    } finally {
      setLoadingSimilar(false);
    }
  };

  const handleAddToCart = async () => {
    if (!id) return;

    // Unauthenticated/guest guard: redirect to login and preserve destination
    if (!isAuthenticated || !userId) {
      navigate('/login', {
        state: {
          from: { pathname: location.pathname + location.search }
        }
      });
      return;
    }

    setAddingToCart(true);
    await eventService.trackAddToCart(userId, id);

    // Add to local cart
    const cart = JSON.parse(localStorage.getItem('cart') || '[]');
    cart.push({ productId: id, name: product?.name, price: product?.price });
    localStorage.setItem('cart', JSON.stringify(cart));
    window.dispatchEvent(new Event('cart-updated'));

    setAddingToCart(false);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2500);
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 sm:px-6 py-12 max-w-7xl">
        <div className="bg-white rounded-3xl p-8 border border-slate-200/80 animate-pulse grid grid-cols-1 md:grid-cols-2 gap-8 shadow-sm">
          <div className="h-96 bg-slate-100 rounded-2xl" />
          <div className="space-y-4 py-4">
            <div className="h-4 bg-slate-100 rounded w-1/4" />
            <div className="h-8 bg-slate-100 rounded w-3/4" />
            <div className="h-6 bg-slate-100 rounded w-1/3" />
            <div className="h-24 bg-slate-100 rounded" />
            <div className="h-12 bg-slate-100 rounded w-full" />
          </div>
        </div>
      </div>
    );
  }

  if (!product) {
    return (
      <div className="container mx-auto px-4 sm:px-6 py-16 max-w-2xl text-center">
        <div className="bg-white border border-slate-200 rounded-3xl p-10 shadow-sm">
          <div className="w-12 h-12 bg-rose-50 text-rose-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-slate-800 mb-2">Product Not Found</h2>
          <p className="text-sm text-slate-500 mb-6">The requested product could not be located in our active catalog.</p>
          <Link
            to="/products"
            className="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition-colors inline-block"
          >
            Browse Products
          </Link>
        </div>
      </div>
    );
  }

  const formattedPrice = product.price
    ? `₹${typeof product.price === 'string' ? parseFloat(product.price).toFixed(2) : product.price.toFixed(2)}`
    : 'Price not listed';

  return (
    <div className="container mx-auto px-4 sm:px-6 py-6 sm:py-10 max-w-7xl">
      <Toast show={showToast} message="Product added to your cart!" type="success" />

      {/* Breadcrumbs */}
      <nav className="flex items-center gap-2 text-xs text-slate-500 mb-6 font-medium">
        <Link to="/" className="hover:text-slate-800 transition-colors">Home</Link>
        <span>/</span>
        <Link to="/products" className="hover:text-slate-800 transition-colors">Products</Link>
        {product.category_name && (
          <>
            <span>/</span>
            <span className="text-slate-700">{product.category_name}</span>
          </>
        )}
      </nav>

      {/* Product Details Hero Card */}
      <div className="bg-white rounded-3xl shadow-sm border border-slate-200/80 p-6 sm:p-10 mb-14">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 lg:gap-12 items-start">
          {/* Left: Product Image Stage */}
          <div className="bg-slate-50 rounded-2xl p-8 border border-slate-100 flex items-center justify-center min-h-[380px] max-h-[460px] overflow-hidden relative">
            {product.image_url ? (
              <img
                src={product.image_url}
                alt={product.name}
                className="max-h-full max-w-full object-contain hover:scale-105 transition-transform duration-300 ease-out"
                loading="eager"
              />
            ) : (
              <div className="flex flex-col items-center justify-center text-slate-300">
                <svg className="w-16 h-16 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <span className="text-xs text-slate-400 font-medium">Image unavailable</span>
              </div>
            )}
          </div>

          {/* Right: Product Metadata & Purchasing */}
          <div className="flex flex-col justify-between">
            <div>
              {/* Category Pill */}
              {product.category_name && (
                <span className="inline-block px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 text-xs font-semibold uppercase tracking-wider mb-3 border border-indigo-100/60">
                  {product.category_name}
                </span>
              )}

              {/* Title */}
              <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight mb-4 leading-snug">
                {product.name}
              </h1>

              {/* Price & Availability Tag */}
              <div className="flex items-baseline gap-4 mb-6 pb-6 border-b border-slate-100">
                <span className="text-3xl sm:text-4xl font-extrabold text-slate-900 tracking-tight">
                  {formattedPrice}
                </span>
                <span className="text-xs font-semibold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200/60">
                  Available in Catalog
                </span>
              </div>

              {/* Structured Description Component */}
              <div className="mb-8">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                  Product Overview & Specs
                </h3>
                <div className="bg-slate-50/70 rounded-2xl p-4 sm:p-5 border border-slate-100">
                  <StructuredDescription description={product.description || 'No detailed specifications provided.'} />
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="pt-4 border-t border-slate-100 flex flex-col sm:flex-row gap-3">
              <button
                onClick={handleAddToCart}
                disabled={addingToCart}
                className="flex-1 px-8 py-3.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm transition-all duration-200 shadow-md shadow-blue-600/20 disabled:bg-slate-400 flex items-center justify-center gap-2"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
                {addingToCart ? 'Adding to Cart...' : 'Add to Shopping Cart'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Similar Products Section */}
      <section className="mb-12">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
              Related & Similar Products
            </h2>
            <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
              Items frequently explored alongside this product.
            </p>
          </div>
        </div>

        {loadingSimilar ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="bg-white rounded-2xl border border-slate-200/80 p-4 animate-pulse h-72 flex flex-col justify-between">
                <div className="h-36 bg-slate-100 rounded-xl" />
                <div className="space-y-2">
                  <div className="h-3 bg-slate-100 rounded w-3/4" />
                  <div className="h-4 bg-slate-100 rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : similarProducts.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-2xl p-8 text-center text-xs text-slate-500">
            No related products available for this item.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {similarProducts.map((rec) => (
              <ProductCard
                key={rec.product_id}
                id={rec.product_id}
                name={rec.name}
                price={rec.price}
                imageUrl={rec.image_url}
                categoryName={rec.category_name}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
};

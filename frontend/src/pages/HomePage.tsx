import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { catalogService } from '../services/catalogService';
import type { Product } from '../services/catalogService';
import { recommendationService } from '../services/recommendationService';
import type { Recommendation } from '../services/recommendationService';
import { sessionService } from '../services/sessionService';
import { readinessService } from '../services/readinessService';

export const HomePage: React.FC = () => {
  const { userId } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [currentPage, setCurrentPage] = useState(0);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [loadingRecs, setLoadingRecs] = useState(true);
  const [isWarmingUp, setIsWarmingUp] = useState(false);
  
  const itemsPerPage = 16; // 4x4 grid
  const totalPages = Math.ceil(products.length / itemsPerPage);
  const currentProducts = products.slice(currentPage * itemsPerPage, (currentPage + 1) * itemsPerPage);

  useEffect(() => {
    checkReadinessAndLoad();
  }, [userId]);

  const checkReadinessAndLoad = async () => {
    try {
      const readyState = await readinessService.checkReadiness().catch(() => null);
      if (readyState && readyState.status === 'warming_up') {
        setIsWarmingUp(true);
      } else {
        setIsWarmingUp(false);
      }
    } catch {
      // Continue gracefully
    }

    loadProducts();
    loadRecommendations();
  };

  const loadProducts = async () => {
    try {
      const response = await catalogService.getProducts({ limit: 48 });
      if (Array.isArray(response.products)) {
        setProducts(response.products);
      } else {
        setProducts([]);
      }
    } catch (error) {
      console.error('Failed to load products:', error);
      setProducts([]);
    } finally {
      setLoadingProducts(false);
    }
  };

  const loadRecommendations = async () => {
    setLoadingRecs(true);
    try {
      const activeSessionId = sessionService.getSessionId(userId);
      const response = await recommendationService.getRecommendationsForUser(
        activeSessionId,
        8
      );
      setRecommendations(response.recommendations || []);
      setIsWarmingUp(false);
    } catch (error) {
      console.error('Failed to load recommendations:', error);
    } finally {
      setLoadingRecs(false);
    }
  };

  return (
    <div className="container mx-auto px-4 sm:px-6 py-6 sm:py-10 max-w-7xl">
      {/* Cold Start / Service Warm-up Banner */}
      {isWarmingUp && (
        <div className="mb-6 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 text-blue-800 px-4 py-3 rounded-xl flex items-center justify-between text-sm shadow-sm animate-pulse">
          <div className="flex items-center gap-2.5">
            <svg className="animate-spin h-4 w-4 text-blue-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span>Getting Atlas ready — initializing cloud service containers...</span>
          </div>
          <span className="text-xs text-blue-600 font-medium hidden sm:inline">Automatic warm-up</span>
        </div>
      )}

      {/* Hero Section */}
      <section className="mb-10 sm:mb-14">
        <div className="bg-gradient-to-br from-slate-900 via-slate-800 to-indigo-950 text-white rounded-2xl p-6 sm:p-10 mb-8 shadow-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 -mt-8 -mr-8 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="relative z-10 max-w-2xl">
            <span className="inline-block text-xs font-semibold tracking-wider text-blue-400 uppercase mb-2">
              Next-Generation Commerce
            </span>
            <h1 className="text-3xl sm:text-4xl md:text-5xl font-extrabold tracking-tight mb-3">
              Discover Products Curated for You
            </h1>
            <p className="text-sm sm:text-base text-gray-300 leading-relaxed mb-6">
              Explore trending items and personalized recommendations tailored to your browsing context.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Link
                to="/products"
                className="bg-blue-600 hover:bg-blue-700 text-white font-medium px-5 py-2.5 rounded-lg transition-colors text-sm shadow-md"
              >
                Browse All Products
              </Link>
              <a
                href="#recommendations"
                className="bg-white/10 hover:bg-white/20 text-white font-medium px-5 py-2.5 rounded-lg transition-colors text-sm backdrop-blur-sm"
              >
                View Recommendations
              </a>
            </div>
          </div>
        </div>

        {/* Recommendations Section */}
        <div id="recommendations">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-xl sm:text-2xl font-bold text-gray-900 tracking-tight">
                Recommended For You
              </h2>
              <p className="text-xs sm:text-sm text-gray-500 mt-0.5">
                Curated selections ranked by relevance and browsing intent.
              </p>
            </div>
            {recommendations.length > 0 && (
              <span className="text-xs font-medium text-gray-500 bg-gray-100 px-3 py-1 rounded-full">
                {recommendations.length} picks
              </span>
            )}
          </div>

          {loadingRecs ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="bg-white rounded-xl shadow-sm p-4 border border-gray-200/80 animate-pulse h-80 flex flex-col justify-between">
                  <div className="h-36 bg-gray-100 rounded-lg mb-3" />
                  <div className="h-4 bg-gray-100 rounded w-3/4 mb-2" />
                  <div className="h-4 bg-gray-100 rounded w-1/2 mb-3" />
                  <div className="h-6 bg-gray-100 rounded w-1/3 mt-auto" />
                </div>
              ))}
            </div>
          ) : recommendations.length === 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl p-8 text-center max-w-lg mx-auto">
              <p className="text-gray-700 font-medium">Browse our catalog to build your recommendation profile</p>
              <p className="text-xs text-gray-500 mt-1">Interact with products to discover personalized suggestions.</p>
              <Link to="/products" className="inline-block mt-4 text-sm text-blue-600 hover:underline font-medium">
                Explore catalog &rarr;
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6">
              {recommendations.slice(0, 8).map((rec) => (
                <Link
                  key={rec.product_id}
                  to={`/products/${rec.product_id}`}
                  className="bg-white rounded-xl shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 overflow-hidden group border border-gray-200/80 flex flex-col h-[340px]"
                >
                  {/* Image Container */}
                  <div className="h-40 flex items-center justify-center bg-gray-50 p-4 relative overflow-hidden">
                    {rec.image_url ? (
                      <img
                        src={rec.image_url}
                        alt={rec.name || 'Product'}
                        className="max-h-full max-w-full object-contain group-hover:scale-105 transition-transform duration-300"
                        loading="lazy"
                        decoding="async"
                        onError={(e) => {
                          e.currentTarget.style.display = 'none';
                          e.currentTarget.parentElement!.innerHTML = `
                            <div class="flex items-center justify-center h-full">
                              <svg class="w-12 h-12 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                              </svg>
                            </div>
                          `;
                        }}
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full">
                        <svg className="w-12 h-12 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                      </div>
                    )}
                  </div>

                  {/* Content Container */}
                  <div className="flex flex-col flex-1 p-4">
                    {/* Category Tag */}
                    {rec.category_name && (
                      <span className="text-[11px] font-medium text-indigo-600 uppercase tracking-wider mb-1 line-clamp-1">
                        {rec.category_name}
                      </span>
                    )}

                    {/* Title */}
                    <h3 className="text-xs font-semibold text-gray-800 line-clamp-2 leading-relaxed mb-2">
                      {rec.name || rec.product_id}
                    </h3>

                    {/* Price */}
                    <div className="mt-auto pt-2 flex items-center justify-between border-t border-gray-100">
                      <div className="text-base font-bold text-gray-900">
                        {rec.price ? `₹${typeof rec.price === 'string' ? parseFloat(rec.price).toFixed(2) : rec.price.toFixed(2)}` : ''}
                      </div>
                      <span className="text-xs text-blue-600 font-medium group-hover:translate-x-0.5 transition-transform">
                        View &rarr;
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Catalog Grid Section */}
      <section>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-gray-900 tracking-tight">
              Explore All Products
            </h2>
            <p className="text-xs sm:text-sm text-gray-500 mt-0.5">
              Browse our comprehensive collection across all categories.
            </p>
          </div>
          <Link 
            to="/products" 
            className="text-blue-600 hover:text-blue-700 font-medium text-sm flex items-center gap-1"
          >
            View All
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
        
        {loadingProducts ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6 mb-8">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="bg-white rounded-xl shadow-sm p-4 border border-gray-200/80 animate-pulse h-80 flex flex-col justify-between">
                <div className="h-36 bg-gray-100 rounded-lg mb-3" />
                <div className="h-4 bg-gray-100 rounded w-3/4 mb-2" />
                <div className="h-4 bg-gray-100 rounded w-1/2 mb-2" />
                <div className="h-6 bg-gray-100 rounded w-1/3 mt-auto" />
              </div>
            ))}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6 mb-8">
              {currentProducts.map((product) => (
                <Link
                  key={product.id}
                  to={`/products/${product.id}`}
                  className="bg-white rounded-xl shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 overflow-hidden group border border-gray-200/80 flex flex-col h-[340px]"
                >
                  <div className="h-40 flex items-center justify-center bg-gray-50 p-4 relative overflow-hidden">
                    {product.image_url ? (
                      <img
                        src={product.image_url}
                        alt={product.name}
                        className="max-h-full max-w-full object-contain group-hover:scale-105 transition-transform duration-300"
                        loading="lazy"
                        decoding="async"
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full">
                        <svg className="w-12 h-12 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col flex-1 p-4">
                    {product.category_name && (
                      <span className="text-[11px] font-medium text-indigo-600 uppercase tracking-wider mb-1 line-clamp-1">
                        {product.category_name}
                      </span>
                    )}
                    <h3 className="text-xs font-semibold text-gray-800 line-clamp-2 leading-relaxed mb-2">
                      {product.name}
                    </h3>
                    <div className="mt-auto pt-2 flex items-center justify-between border-t border-gray-100">
                      <div className="text-base font-bold text-gray-900">
                        {product.price ? `₹${typeof product.price === 'string' ? parseFloat(product.price).toFixed(2) : product.price.toFixed(2)}` : ''}
                      </div>
                      <span className="text-xs text-blue-600 font-medium group-hover:translate-x-0.5 transition-transform">
                        View &rarr;
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
            
            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div className="flex justify-center items-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(0, currentPage - 1))}
                  disabled={currentPage === 0}
                  className="px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium text-sm rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors shadow-sm"
                >
                  Previous
                </button>
                <span className="text-xs font-medium text-gray-500 px-3">
                  Page {currentPage + 1} of {totalPages}
                </span>
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages - 1, currentPage + 1))}
                  disabled={currentPage === totalPages - 1}
                  className="px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium text-sm rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors shadow-sm"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
};

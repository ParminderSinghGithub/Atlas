import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { catalogService } from '../services/catalogService';
import type { Product } from '../services/catalogService';
import { recommendationService } from '../services/recommendationService';
import type { Recommendation } from '../services/recommendationService';

export const HomePage: React.FC = () => {
  const { userId } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [currentPage, setCurrentPage] = useState(0);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [strategyUsed, setStrategyUsed] = useState<string>('');
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [loadingRecs, setLoadingRecs] = useState(true);
  
  const itemsPerPage = 16; // 4x4 grid
  const totalPages = Math.ceil(products.length / itemsPerPage);
  const currentProducts = products.slice(currentPage * itemsPerPage, (currentPage + 1) * itemsPerPage);

  useEffect(() => {
    loadProducts();
    if (userId) {
      loadRecommendations();
    }
  }, [userId]);

  const loadProducts = async () => {
    try {
      const response = await catalogService.getProducts({ limit: 48 }); // Load more for pagination
      console.log('[HOME] Products API Response:', response);
      if (Array.isArray(response.products)) {
        setProducts(response.products);
      } else {
        console.error('[HOME] Response.products is not an array:', typeof response.products);
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
    if (!userId) return;
    
    try {
      const response = await recommendationService.getRecommendationsForUser(
        userId,
        8
      );
      setRecommendations(response.recommendations);
      setStrategyUsed(response.strategy_used);
      console.log(`[HOME] Recommendation strategy: ${response.strategy_used}`);
    } catch (error) {
      console.error('Failed to load recommendations:', error);
    } finally {
      setLoadingRecs(false);
    }
  };

  return (
    <div className="container mx-auto px-4 sm:px-6 py-4 sm:py-8">
      {/* Hero Section with Recommendations */}
      <section className="mb-8 sm:mb-12">
        <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-xl p-4 sm:p-8 mb-6 sm:mb-8">
          <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold mb-2 bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Personalized Recommendations
          </h1>
          <p className="text-sm sm:text-base text-gray-600">Personalized using historical behavior and recent session activity</p>
        </div>
        
        {loadingRecs ? (
          <div className="flex justify-center items-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        ) : recommendations.length === 0 ? (
          <div className="bg-gradient-to-r from-yellow-50 to-orange-50 border-l-4 border-yellow-400 px-6 py-4 rounded-lg">
            <p className="text-gray-700">
              <span className="font-semibold">Getting started:</span> Browse products to help us learn your preferences and provide personalized recommendations!
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-gray-800">
                Recommended For You
              </h2>
              <div className="flex items-center gap-2 text-sm">
                <span className="px-3 py-1 bg-blue-100 text-blue-700 rounded-full font-medium">
                  {strategyUsed.replace(/_/g, ' ').toUpperCase()}
                </span>
                <span className="text-gray-500">{recommendations.length} items</span>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
              {recommendations.slice(0, 8).map((rec) => (
                <Link
                  key={rec.product_id}
                  to={`/products/${rec.product_id}`}
                  className="bg-white rounded-lg shadow-sm hover:shadow-xl transition-all duration-300 overflow-hidden group border border-gray-200 relative"
                >
                  {rec.image_url && (
                    <div className="aspect-square bg-gray-100 overflow-hidden">
                      <img
                        src={rec.image_url}
                        alt={rec.name || 'Product'}
                        className="w-full h-full object-contain group-hover:scale-105 transition-transform duration-300"
                      />
                    </div>
                  )}
                  <div className="p-4">
                    <div className="text-sm font-semibold mb-2 truncate text-gray-800">
                      {rec.name || rec.product_id}
                    </div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs bg-purple-100 text-purple-700 px-2 py-1 rounded">
                        Rank #{rec.rank}
                      </span>
                      <span className="text-xs text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                        Score: {rec.score.toFixed(2)}
                      </span>
                    </div>
                    {rec.price && (
                      <div className="text-lg font-bold text-green-600">
                        ₹{typeof rec.price === 'string' ? parseFloat(rec.price).toFixed(2) : rec.price.toFixed(2)}
                      </div>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </section>

      {/* Products Grid Section */}
      <section>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-800">Browse All Products</h2>
          <Link 
            to="/products" 
            className="text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
          >
            View All
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
        
        {loadingProducts ? (
          <div className="flex justify-center items-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6 mb-8">
              {currentProducts.map((product) => (
                <Link
                  key={product.id}
                  to={`/products/${product.id}`}
                  className="bg-white rounded-lg shadow-sm hover:shadow-xl transition-all duration-300 overflow-hidden group border border-gray-200"
                >
                  {product.image_url ? (
                    <div className="aspect-square bg-gray-100 overflow-hidden">
                      <img
                        src={product.image_url}
                        alt={product.name}
                        className="w-full h-full object-contain group-hover:scale-105 transition-transform duration-300"
                      />
                    </div>
                  ) : (
                    <div className="aspect-square bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center">
                      <svg className="w-16 h-16 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                    </div>
                  )}
                  <div className="p-4">
                    <h3 className="font-semibold mb-3 text-gray-800 line-clamp-2 min-h-[3rem]">
                      {product.name}
                    </h3>
                    {product.description && (
                      <p className="text-xs text-gray-500 mb-3 line-clamp-2 leading-relaxed">
                        {product.description}
                      </p>
                    )}
                    {product.category_name && (
                      <span className="inline-block text-xs bg-gradient-to-r from-blue-50 to-purple-50 text-blue-700 px-2.5 py-1 rounded-full mb-3 font-medium">
                        {product.category_name}
                      </span>
                    )}
                    <div className="text-xl font-bold text-green-600 mt-2">
                      ₹{typeof product.price === 'string' ? parseFloat(product.price).toFixed(2) : product.price.toFixed(2)}
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
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
                >
                  Previous
                </button>
                <span className="text-gray-600 px-4">
                  Page {currentPage + 1} of {totalPages}
                </span>
                <button
                  onClick={() => setCurrentPage(Math.min(totalPages - 1, currentPage + 1))}
                  disabled={currentPage === totalPages - 1}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
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

import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { catalogService } from '../services/catalogService';
import type { Product, Category } from '../services/catalogService';
import { recommendationService } from '../services/recommendationService';
import type { Recommendation } from '../services/recommendationService';
import { sessionService } from '../services/sessionService';
import { ProductCard } from '../components/ui/ProductCard';
import { GridSkeleton } from '../components/ui/Skeleton';

export const HomePage: React.FC = () => {
  const { userId } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [currentPage, setCurrentPage] = useState(0);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [loadingRecs, setLoadingRecs] = useState(true);

  const itemsPerPage = 16;
  const totalPages = Math.ceil(products.length / itemsPerPage);
  const currentProducts = products.slice(currentPage * itemsPerPage, (currentPage + 1) * itemsPerPage);

  useEffect(() => {
    loadCategories();
    loadProducts();
    loadRecommendations();
  }, [userId]);

  const loadCategories = async () => {
    try {
      const cats = await catalogService.getCategories();
      if (Array.isArray(cats)) {
        setCategories(cats.slice(0, 6));
      }
    } catch {
      // Graceful fallback
    }
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
      console.error('Failed to load catalog products:', error);
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
    } catch (error) {
      console.error('Failed to load recommendations:', error);
    } finally {
      setLoadingRecs(false);
    }
  };

  return (
    <div className="container mx-auto px-4 sm:px-6 py-6 sm:py-10 max-w-7xl">
      {/* Hero Banner */}
      <section className="mb-12 sm:mb-16">
        <div className="bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white rounded-3xl p-8 sm:p-12 shadow-2xl relative overflow-hidden border border-slate-800">
          {/* Subtle glow effect */}
          <div className="absolute -top-24 -right-24 w-96 h-96 bg-blue-500/10 rounded-full blur-[100px] pointer-events-none" />
          <div className="absolute -bottom-24 -left-24 w-80 h-80 bg-indigo-500/10 rounded-full blur-[90px] pointer-events-none" />

          <div className="relative z-10 max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-400/20 text-blue-400 text-xs font-semibold uppercase tracking-wider mb-4">
              <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
              Intelligent Product Discovery
            </div>
            <h1 className="text-3xl sm:text-4xl md:text-5xl font-extrabold tracking-tight mb-4 leading-tight">
              Curated Recommendations.
              <br />
              <span className="bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
                Tailored for Every Session.
              </span>
            </h1>
            <p className="text-sm sm:text-base text-slate-300 font-normal leading-relaxed mb-8">
              Explore thousands of products ranked by relevance, session preferences, and catalog similarity.
            </p>

            <div className="flex flex-wrap items-center gap-3">
              <Link
                to="/products"
                className="px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition-all duration-200 shadow-lg shadow-blue-600/30 flex items-center gap-2 hover:translate-x-0.5"
              >
                Browse Catalog
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </Link>
              <a
                href="#recommendations"
                className="px-6 py-3 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 text-slate-200 text-sm font-medium transition-colors border border-slate-700/60 backdrop-blur-sm"
              >
                View Recommendations
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Category Discovery Pills */}
      {categories.length > 0 && (
        <section className="mb-12">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Popular Categories
            </h2>
            <Link to="/products" className="text-xs font-semibold text-blue-600 hover:text-blue-700">
              All categories &rarr;
            </Link>
          </div>
          <div className="flex flex-wrap gap-2.5">
            {categories.map((cat) => (
              <Link
                key={cat.id}
                to={`/products?category=${cat.id}`}
                className="px-4 py-2 rounded-xl bg-white border border-slate-200/80 text-xs sm:text-sm font-semibold text-slate-700 hover:text-blue-600 hover:border-blue-300 hover:shadow-sm transition-all"
              >
                {cat.name}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Recommendations Section */}
      <section id="recommendations" className="mb-16">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
              Recommended For You
            </h2>
            <p className="text-xs sm:text-sm text-slate-500 mt-1">
              Curated items aligned with your current session and browsing context.
            </p>
          </div>
          {recommendations.length > 0 && (
            <span className="hidden sm:inline-block text-xs font-medium text-slate-500 bg-slate-100 px-3 py-1 rounded-full border border-slate-200/60">
              {recommendations.length} items curated
            </span>
          )}
        </div>

        {loadingRecs ? (
          <GridSkeleton count={4} />
        ) : recommendations.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-2xl p-8 text-center max-w-md mx-auto shadow-sm">
            <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 mx-auto flex items-center justify-center mb-3">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-slate-800">Discovering products...</p>
            <p className="text-xs text-slate-500 mt-1">Browse our catalog to build your recommendation profile.</p>
            <Link
              to="/products"
              className="inline-block mt-4 text-xs font-semibold text-blue-600 hover:underline"
            >
              Explore Catalog &rarr;
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6">
            {recommendations.slice(0, 8).map((rec, idx) => (
              <ProductCard
                key={rec.product_id}
                id={rec.product_id}
                name={rec.name}
                price={rec.price}
                imageUrl={rec.image_url}
                categoryName={rec.category_name}
                rank={idx + 1}
              />
            ))}
          </div>
        )}
      </section>

      {/* Catalog Grid Section */}
      <section>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
              Explore All Products
            </h2>
            <p className="text-xs sm:text-sm text-slate-500 mt-1">
              Browse our comprehensive collection across all categories.
            </p>
          </div>
          <Link
            to="/products"
            className="text-xs sm:text-sm font-semibold text-blue-600 hover:text-blue-700 flex items-center gap-1"
          >
            View Full Catalog
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>

        {loadingProducts ? (
          <GridSkeleton count={8} />
        ) : products.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-2xl p-12 text-center text-slate-500">
            No products available at the moment.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6">
              {currentProducts.map((product) => (
                <ProductCard
                  key={product.id}
                  id={product.id}
                  name={product.name}
                  price={product.price}
                  imageUrl={product.image_url}
                  categoryName={product.category_name}
                />
              ))}
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div className="flex justify-center items-center gap-3 mt-10">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
                  disabled={currentPage === 0}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200/80 text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  Previous
                </button>
                <span className="text-xs font-medium text-slate-500">
                  Page {currentPage + 1} of {totalPages}
                </span>
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={currentPage >= totalPages - 1}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-white border border-slate-200/80 text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
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

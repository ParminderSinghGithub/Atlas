import React, { useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useReadiness } from '../contexts/ReadinessContext';
import { catalogService } from '../services/catalogService';
import type { Product, Category } from '../services/catalogService';
import { sessionService } from '../services/sessionService';
import { ProductCard } from '../components/ui/ProductCard';
import { GridSkeleton } from '../components/ui/Skeleton';

export const ProductListPage: React.FC = () => {
  const { userId } = useAuth();
  const { isReadyOrDegraded } = useReadiness();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialCategory = searchParams.get('category') || '';

  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>(initialCategory);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('default');
  const [currentCursor, setCurrentCursor] = useState<string | null>(null);
  const [prevCursors, setPrevCursors] = useState<(string | null)[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const perPage = 20;
  const nextCursorRef = useRef<string | null>(null);

  useEffect(() => {
    if (!isReadyOrDegraded) return;
    loadCategories();
  }, [isReadyOrDegraded]);

  useEffect(() => {
    const catParam = searchParams.get('category') || '';
    setSelectedCategory(catParam);
  }, [searchParams]);

  useEffect(() => {
    if (!isReadyOrDegraded) return;
    loadProducts();
  }, [currentCursor, selectedCategory, isReadyOrDegraded]);

  const loadCategories = async () => {
    try {
      const cats = await catalogService.getCategories();
      if (Array.isArray(cats)) {
        setCategories(cats);
      } else {
        setCategories([]);
      }
    } catch {
      setCategories([]);
    }
  };

  const loadProducts = async () => {
    setLoading(true);
    try {
      const response = await catalogService.getProducts({
        cursor: currentCursor || undefined,
        limit: perPage,
        category_id: selectedCategory || undefined,
      });

      if (Array.isArray(response.products)) {
        setProducts(response.products);
      } else {
        setProducts([]);
      }

      const nextCursor = response.pagination?.next_cursor || null;
      setHasMore(!!nextCursor && response.pagination?.has_more);
      nextCursorRef.current = nextCursor;
    } catch (error) {
      console.error('Failed to load catalog products:', error);
      setProducts([]);
    } finally {
      setLoading(false);
    }
  };

  const handleCategorySelect = (categoryId: string) => {
    setSelectedCategory(categoryId);
    setCurrentCursor(null);
    setPrevCursors([]);

    if (categoryId) {
      setSearchParams({ category: categoryId });
      const activeSessionId = sessionService.getSessionId(userId);
      const catObj = categories.find((c) => c.id === categoryId);
      const slugOrName = catObj?.slug || catObj?.name?.toLowerCase().replace(/\s+/g, '-') || categoryId;
      sessionService.trackCategoryView(activeSessionId, String(slugOrName));
    } else {
      setSearchParams({});
    }
  };

  const handleNextPage = () => {
    if (nextCursorRef.current) {
      setPrevCursors((prev) => [...prev, currentCursor]);
      setCurrentCursor(nextCursorRef.current);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const handlePrevPage = () => {
    if (prevCursors.length > 0) {
      const newPrev = [...prevCursors];
      const prev = newPrev.pop();
      setPrevCursors(newPrev);
      setCurrentCursor(prev || null);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  // Filter & sort
  let processedProducts = products.filter((product) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      product.name.toLowerCase().includes(q) ||
      (product.description && product.description.toLowerCase().includes(q))
    );
  });

  if (sortBy === 'price_asc') {
    processedProducts = [...processedProducts].sort((a, b) => (Number(a.price) || 0) - (Number(b.price) || 0));
  } else if (sortBy === 'price_desc') {
    processedProducts = [...processedProducts].sort((a, b) => (Number(b.price) || 0) - (Number(a.price) || 0));
  } else if (sortBy === 'name_asc') {
    processedProducts = [...processedProducts].sort((a, b) => a.name.localeCompare(b.name));
  }

  return (
    <div className="container mx-auto px-4 sm:px-6 py-6 sm:py-10 max-w-7xl">
      {/* Header & Title */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
            Product Catalog
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Browse through our active collection of quality products.
          </p>
        </div>

        {/* Search & Sort Controls */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          {/* Search Box */}
          <div className="relative min-w-[240px]">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search products..."
              className="w-full pl-9 pr-8 py-2 rounded-xl border border-slate-200/80 bg-white text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all shadow-sm"
            />
            <svg
              className="w-4 h-4 text-slate-400 absolute left-3 top-2.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-600 text-xs"
              >
                ✕
              </button>
            )}
          </div>

          {/* Sort Dropdown */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="px-3.5 py-2 rounded-xl border border-slate-200/80 bg-white text-xs sm:text-sm font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all shadow-sm"
          >
            <option value="default">Featured</option>
            <option value="price_asc">Price: Low to High</option>
            <option value="price_desc">Price: High to Low</option>
            <option value="name_asc">Name: A-Z</option>
          </select>
        </div>
      </div>

      {/* Category Filter Pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-4 mb-8 no-scrollbar">
        <button
          onClick={() => handleCategorySelect('')}
          className={`px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all ${
            selectedCategory === ''
              ? 'bg-slate-900 text-white shadow-md'
              : 'bg-white text-slate-600 border border-slate-200/80 hover:border-slate-300'
          }`}
        >
          All Categories
        </button>
        {categories.map((cat) => (
          <button
            key={cat.id}
            onClick={() => handleCategorySelect(cat.id)}
            className={`px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all ${
              selectedCategory === cat.id
                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                : 'bg-white text-slate-600 border border-slate-200/80 hover:border-slate-300'
            }`}
          >
            {cat.name}
          </button>
        ))}
      </div>

      {/* Main Products Grid */}
      {loading ? (
        <GridSkeleton count={8} />
      ) : processedProducts.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-3xl p-12 text-center max-w-lg mx-auto shadow-sm">
          <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 mx-auto flex items-center justify-center mb-3">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-slate-800 mb-1">No products match your criteria</h3>
          <p className="text-xs text-slate-500 mb-4">Try clearing filters or searching for different keywords.</p>
          <button
            onClick={() => {
              setSearchQuery('');
              handleCategorySelect('');
            }}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition-colors"
          >
            Reset Filters
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6">
            {processedProducts.map((product) => (
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

          {/* Cursor-based Pagination */}
          <div className="flex justify-center items-center gap-3 mt-12 pt-6 border-t border-slate-200/60">
            <button
              onClick={handlePrevPage}
              disabled={prevCursors.length === 0}
              className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-white border border-slate-200/80 text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              &larr; Previous Page
            </button>
            <span className="text-xs font-medium text-slate-500">
              Page {prevCursors.length + 1}
            </span>
            <button
              onClick={handleNextPage}
              disabled={!hasMore}
              className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-white border border-slate-200/80 text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              Next Page &rarr;
            </button>
          </div>
        </>
      )}
    </div>
  );
};

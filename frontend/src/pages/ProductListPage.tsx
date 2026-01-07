import React, { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { catalogService } from '../services/catalogService';
import type { Product, Category } from '../services/catalogService';
import { sessionService } from '../services/sessionService';

export const ProductListPage: React.FC = () => {
  const { userId } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [currentCursor, setCurrentCursor] = useState<string | null>(null);
  const [prevCursors, setPrevCursors] = useState<(string | null)[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const perPage = 20;
  const nextCursorRef = useRef<string | null>(null);

  useEffect(() => {
    loadCategories();
  }, []);

  useEffect(() => {
    loadProducts();
  }, [currentCursor, selectedCategory]);

  const loadCategories = async () => {
    try {
      const cats = await catalogService.getCategories();
      console.log('[PRODUCTS] Categories response:', cats);
      // Safety check: ensure categories is an array
      if (Array.isArray(cats)) {
        setCategories(cats);
      } else {
        console.error('[PRODUCTS] Categories is not an array:', typeof cats);
        setCategories([]);
      }
    } catch (error) {
      console.error('Failed to load categories:', error);
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
      console.log('[PRODUCTS] API Response:', response);
      console.log('[PRODUCTS] Products array:', response.products);
      
      // Safety check: ensure products is an array
      if (Array.isArray(response.products)) {
        setProducts(response.products);
      } else {
        console.error('[PRODUCTS] Response.products is not an array:', typeof response.products);
        setProducts([]);
      }
      
      // Store next cursor and has_more flag
      const nextCursor = response.pagination?.next_cursor || null;
      setHasMore(!!nextCursor && response.pagination?.has_more);
      
      // Store the next cursor for the "Next" button
      nextCursorRef.current = nextCursor;
    } catch (error) {
      console.error('Failed to load products:', error);
      setProducts([]); // Set empty array on error
    } finally {
      setLoading(false);
    }
  };

  const handleCategoryChange = (categoryId: string) => {
    setSelectedCategory(categoryId);
    setCurrentCursor(null);
    setPrevCursors([]);
    
    // Track category view for session re-ranking
    if (userId && categoryId) {
      sessionService.trackCategoryView(userId, categoryId);
    }
  };

  // Filter products by search query
  const filteredProducts = products.filter((product) =>
    product.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (product.description && product.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className="container mx-auto px-6 py-8">
      <h1 className="text-3xl font-bold mb-8 text-gray-800">Product Catalog</h1>

      {/* Search and Filter Section */}
      <div className="bg-white rounded-lg shadow-sm p-6 mb-8 border border-gray-200">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Search Bar */}
          <div>
            <label className="block text-sm font-semibold mb-2 text-gray-700">Search Products</label>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name or description..."
                className="w-full border border-gray-300 rounded-lg px-4 py-2 pl-10 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <svg 
                xmlns="http://www.w3.org/2000/svg" 
                className="h-5 w-5 absolute left-3 top-2.5 text-gray-400" 
                fill="none" 
                viewBox="0 0 24 24" 
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
          </div>

          {/* Category Filter */}
          <div>
            <label className="block text-sm font-semibold mb-2 text-gray-700">Filter by Category</label>
            <select
              value={selectedCategory}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All Categories</option>
              {Array.isArray(categories) && categories.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Results Count */}
        <div className="mt-4 text-sm text-gray-600">
          {searchQuery && (
            <span>Showing {filteredProducts.length} results for "{searchQuery}"</span>
          )}
          {!searchQuery && (
            <span>Showing {products.length} products</span>
          )}
        </div>
      </div>

      {/* Product Grid */}
      {loading ? (
        <div className="flex justify-center items-center py-16">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      ) : filteredProducts.length === 0 ? (
        <div className="text-center py-16">
          <svg className="mx-auto h-16 w-16 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-gray-600 text-lg">No products found matching your criteria</p>
          <button
            onClick={() => {
              setSearchQuery('');
              setSelectedCategory('');
            }}
            className="mt-4 text-blue-600 hover:text-blue-700 font-medium"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            {filteredProducts.map((product) => (
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

          {/* Pagination */}
          {!searchQuery && (
            <div className="flex justify-center items-center gap-2 mb-8">
              <button
                onClick={() => {
                  if (prevCursors.length > 0) {
                    const newPrevCursors = [...prevCursors];
                    const prevCursor = newPrevCursors.pop();
                    setPrevCursors(newPrevCursors);
                    setCurrentCursor(prevCursor || null);
                  }
                }}
                disabled={prevCursors.length === 0}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
              >
                Previous
              </button>
              <span className="text-gray-600 px-4">
                Page {prevCursors.length + 1}
              </span>
              <button
                onClick={() => {
                  if (hasMore && nextCursorRef.current) {
                    setPrevCursors([...prevCursors, currentCursor]);
                    setCurrentCursor(nextCursorRef.current);
                  }
                }}
                disabled={!hasMore}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

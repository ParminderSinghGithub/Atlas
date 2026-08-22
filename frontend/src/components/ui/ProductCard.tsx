import React from 'react';
import { Link } from 'react-router-dom';

export interface ProductCardProps {
  id: string;
  name?: string;
  price?: number | string;
  imageUrl?: string | null;
  categoryName?: string | null;
  rank?: number;
  className?: string;
}

export const ProductCard: React.FC<ProductCardProps> = ({
  id,
  name,
  price,
  imageUrl,
  categoryName,
  rank,
  className = '',
}) => {
  const formattedPrice = price
    ? `₹${typeof price === 'string' ? parseFloat(price).toFixed(2) : price.toFixed(2)}`
    : '';

  return (
    <Link
      to={`/products/${id}`}
      className={`group bg-white rounded-2xl border border-slate-200/80 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all duration-300 flex flex-col overflow-hidden h-[360px] relative ${className}`}
    >
      {/* Optional Rank Badge */}
      {rank && (
        <div className="absolute top-3 left-3 z-10 bg-slate-900/80 backdrop-blur-md text-white text-[11px] font-semibold px-2 py-0.5 rounded-md shadow-sm">
          #{rank}
        </div>
      )}

      {/* Image Container with fixed aspect ratio */}
      <div className="h-44 bg-slate-50 flex items-center justify-center p-4 relative overflow-hidden border-b border-slate-100/80">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={name || 'Product'}
            className="max-h-full max-w-full object-contain group-hover:scale-105 transition-transform duration-300 ease-out"
            loading="lazy"
            decoding="async"
            onError={(e) => {
              e.currentTarget.style.display = 'none';
              if (e.currentTarget.parentElement) {
                e.currentTarget.parentElement.innerHTML = `
                  <div class="flex flex-col items-center justify-center h-full text-slate-300">
                    <svg class="w-10 h-10 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span class="text-[10px] text-slate-400 font-medium">Image unavailable</span>
                  </div>
                `;
              }
            }}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-slate-300">
            <svg className="w-10 h-10 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
        )}
      </div>

      {/* Content Container */}
      <div className="flex flex-col flex-1 p-4 justify-between">
        <div>
          {/* Category Tag */}
          {categoryName && (
            <span className="inline-block text-[11px] font-semibold tracking-wide text-indigo-600 uppercase mb-1 line-clamp-1">
              {categoryName}
            </span>
          )}

          {/* Product Title */}
          <h3 className="text-xs sm:text-sm font-semibold text-slate-800 line-clamp-2 leading-snug group-hover:text-blue-600 transition-colors">
            {name || id}
          </h3>
        </div>

        {/* Price & Action */}
        <div className="pt-2 mt-auto border-t border-slate-100 flex items-center justify-between">
          <div className="text-base font-bold text-slate-900 tracking-tight">
            {formattedPrice}
          </div>
          <span className="text-xs font-semibold text-blue-600 group-hover:translate-x-0.5 transition-transform flex items-center gap-0.5">
            View
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
            </svg>
          </span>
        </div>
      </div>
    </Link>
  );
};

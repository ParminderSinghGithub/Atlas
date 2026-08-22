import React from 'react';

export const CardSkeleton: React.FC = () => {
  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-4 animate-pulse h-[360px] flex flex-col justify-between shadow-sm">
      <div className="h-44 bg-slate-100 rounded-xl mb-3" />
      <div className="space-y-2">
        <div className="h-3 bg-slate-100 rounded w-1/3" />
        <div className="h-4 bg-slate-100 rounded w-5/6" />
        <div className="h-3 bg-slate-100 rounded w-2/3" />
      </div>
      <div className="pt-2 border-t border-slate-100 flex items-center justify-between mt-auto">
        <div className="h-5 bg-slate-100 rounded w-1/4" />
        <div className="h-4 bg-slate-100 rounded w-1/6" />
      </div>
    </div>
  );
};

export const GridSkeleton: React.FC<{ count?: number }> = ({ count = 8 }) => {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 sm:gap-6">
      {[...Array(count)].map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  );
};

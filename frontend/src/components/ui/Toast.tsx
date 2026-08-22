import React from 'react';

export interface ToastProps {
  show: boolean;
  message: string;
  type?: 'success' | 'info' | 'error';
}

export const Toast: React.FC<ToastProps> = ({ show, message, type = 'success' }) => {
  if (!show) return null;

  const bgClasses = {
    success: 'bg-emerald-600 text-white shadow-emerald-500/20',
    info: 'bg-blue-600 text-white shadow-blue-500/20',
    error: 'bg-rose-600 text-white shadow-rose-500/20',
  }[type];

  return (
    <div className={`fixed top-20 right-4 sm:right-8 z-50 px-5 py-3 rounded-xl shadow-xl flex items-center gap-3 animate-fade-in text-sm font-medium border border-white/10 ${bgClasses}`}>
      {type === 'success' && (
        <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
        </svg>
      )}
      <span>{message}</span>
    </div>
  );
};

import React from 'react';
import { useReadiness } from '../contexts/ReadinessContext';

export const StartupExperience: React.FC = () => {
  const {
    readinessState,
    progressPercent,
    currentStatusMessage,
    retryReadiness,
    skipToDegraded,
  } = useReadiness();

  if (readinessState === 'READY' || readinessState === 'DEGRADED') {
    return null;
  }

  const isFailed = readinessState === 'FAILED';

  return (
    <div className="fixed inset-0 z-50 bg-slate-950 flex flex-col items-center justify-center p-6 text-white overflow-hidden select-none">
      {/* Ambient background lighting */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-blue-600/15 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute bottom-1/4 left-1/3 w-64 h-64 bg-indigo-600/10 rounded-full blur-[80px] pointer-events-none" />

      <div className="relative z-10 w-full max-w-md flex flex-col items-center text-center">
        {/* Atlas Logo Mark */}
        <div className="mb-6 relative">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-xl shadow-blue-500/20 border border-white/10">
            <span className="text-3xl font-extrabold text-white tracking-wider">A</span>
          </div>
          {!isFailed && (
            <div className="absolute -inset-1 rounded-2xl bg-gradient-to-tr from-blue-500 to-indigo-500 opacity-30 blur-sm animate-pulse -z-10" />
          )}
        </div>

        {/* Brand & Heading */}
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2 text-white">
          Atlas
        </h1>
        <p className="text-xs sm:text-sm text-slate-400 font-normal mb-8 tracking-wide">
          Getting Atlas ready...
        </p>

        {/* Progress Bar Container */}
        {!isFailed ? (
          <div className="w-full bg-slate-900/80 border border-slate-800 rounded-2xl p-6 backdrop-blur-md shadow-2xl mb-6">
            <div className="w-full bg-slate-800/80 rounded-full h-2 mb-4 overflow-hidden p-0.5 border border-slate-700/50">
              <div
                className="h-full rounded-full bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500 transition-all duration-700 ease-out"
                style={{ width: `${progressPercent}%` }}
              />
            </div>

            {/* Dynamic Status Text */}
            <div className="min-h-[2.5rem] flex items-center justify-center">
              <p className="text-xs sm:text-sm text-slate-300 font-medium animate-fade-in flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-ping" />
                {currentStatusMessage}
              </p>
            </div>

            {/* Subtext explaining cold-start gracefully */}
            <p className="text-[11px] text-slate-500 mt-3 border-t border-slate-800/60 pt-3">
              Initializing microservices after idle period. This happens once on first visit.
            </p>
          </div>
        ) : (
          <div className="w-full bg-red-950/40 border border-red-800/50 rounded-2xl p-6 backdrop-blur-md shadow-2xl mb-6 text-left">
            <h3 className="text-sm font-semibold text-red-300 mb-1">Service Startup Notice</h3>
            <p className="text-xs text-red-200/80 mb-4 leading-relaxed">
              One or more backend containers took longer than expected to start up.
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={retryReadiness}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold transition-colors shadow-sm"
              >
                Retry Connection
              </button>
              <button
                onClick={skipToDegraded}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition-colors"
              >
                Browse Catalog Anyway
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

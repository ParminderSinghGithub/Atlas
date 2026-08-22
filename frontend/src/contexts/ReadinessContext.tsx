import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { readinessService } from '../services/readinessService';
import type { ReadinessResponse } from '../services/readinessService';

export type ReadinessState = 
  | 'INITIALIZING'
  | 'WAKING_SERVICES'
  | 'CHECKING_READINESS'
  | 'READY'
  | 'DEGRADED'
  | 'FAILED';

interface ReadinessContextType {
  readinessState: ReadinessState;
  readinessDetails: ReadinessResponse | null;
  progressPercent: number;
  currentStatusMessage: string;
  isReadyOrDegraded: boolean;
  retryReadiness: () => Promise<void>;
  skipToDegraded: () => void;
}

const ReadinessContext = createContext<ReadinessContextType | undefined>(undefined);

const CACHE_KEY = 'atlas_readiness_established_ts';
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes validity

const STATUS_MESSAGES: Record<ReadinessState, string[]> = {
  INITIALIZING: [
    'Getting Atlas ready...',
    'Checking infrastructure state...',
  ],
  WAKING_SERVICES: [
    'Waking product catalog and recommendation services...',
    'Initializing backend containers...',
    'Establishing database and cache connections...',
  ],
  CHECKING_READINESS: [
    'Verifying microservice health...',
    'Pre-warming recommendation pipelines...',
    'Finalizing platform readiness...',
  ],
  READY: [
    'Atlas is ready.',
  ],
  DEGRADED: [
    'Catalog is ready. Recommendation engine is initializing in background.',
  ],
  FAILED: [
    'Backend services took longer than expected to wake up.',
  ],
};

export const ReadinessProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [readinessState, setReadinessState] = useState<ReadinessState>('INITIALIZING');
  const [readinessDetails, setReadinessDetails] = useState<ReadinessResponse | null>(null);
  const [progressPercent, setProgressPercent] = useState(15);
  const [messageIndex, setMessageIndex] = useState(0);

  const checkIsCachedReady = (): boolean => {
    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        const ts = parseInt(cached, 10);
        if (Date.now() - ts < CACHE_TTL_MS) {
          return true;
        }
      }
    } catch {
      // Fall through on storage error
    }
    return false;
  };

  const markEstablished = () => {
    try {
      sessionStorage.setItem(CACHE_KEY, Date.now().toString());
    } catch {
      // Ignore
    }
  };

  // Rotate messages during active waking states
  useEffect(() => {
    if (readinessState === 'WAKING_SERVICES' || readinessState === 'CHECKING_READINESS') {
      const interval = setInterval(() => {
        setMessageIndex((prev) => prev + 1);
      }, 3500);
      return () => clearInterval(interval);
    }
  }, [readinessState]);

  const performReadinessSequence = useCallback(async () => {
    // 1. Check if already established recently
    if (checkIsCachedReady()) {
      setReadinessState('READY');
      setProgressPercent(100);
      return;
    }

    setReadinessState('WAKING_SERVICES');
    setProgressPercent(20);

    const maxAttempts = 8;
    let attempt = 0;

    while (attempt < maxAttempts) {
      attempt++;
      try {
        if (attempt > 1) {
          setReadinessState('CHECKING_READINESS');
          setProgressPercent(Math.min(30 + attempt * 18, 90));
        }

        const data = await readinessService.checkReadiness(attempt > 1);
        setReadinessDetails(data);

        if (data.status === 'ready') {
          setProgressPercent(100);
          setReadinessState('READY');
          markEstablished();
          return;
        } else if (data.status === 'degraded') {
          // If in early attempts, give recommendation engine a brief chance to finish waking
          if (attempt >= 3) {
            setProgressPercent(100);
            setReadinessState('DEGRADED');
            markEstablished();
            return;
          } else {
            setProgressPercent(Math.min(50 + attempt * 15, 90));
            await new Promise((res) => setTimeout(res, 2500));
          }
        } else if (data.status === 'warming_up') {
          // Continue polling
          setProgressPercent(Math.min(40 + attempt * 8, 88));
          await new Promise((res) => setTimeout(res, 3000));
        } else {
          // Wait and retry
          await new Promise((res) => setTimeout(res, 3500));
        }
      } catch (err) {
        console.warn(`[READINESS] Attempt ${attempt} failed, retrying...`, err);
        if (attempt < maxAttempts) {
          await new Promise((res) => setTimeout(res, 3500));
        }
      }
    }

    // If still not ready after attempts, check if we can at least browse
    try {
      const finalCheck = await readinessService.checkReadiness().catch(() => null);
      if (finalCheck && (finalCheck.status === 'ready' || finalCheck.status === 'degraded')) {
        setReadinessDetails(finalCheck);
        setReadinessState(finalCheck.status === 'ready' ? 'READY' : 'DEGRADED');
        setProgressPercent(100);
        markEstablished();
        return;
      }
    } catch {
      // Fall through
    }

    // Default to degraded to let user browse catalog rather than hard lock
    setReadinessState('DEGRADED');
    setProgressPercent(100);
  }, []);

  useEffect(() => {
    performReadinessSequence();
  }, [performReadinessSequence]);

  const retryReadiness = async () => {
    try {
      sessionStorage.removeItem(CACHE_KEY);
    } catch {
      // Ignore
    }
    setReadinessState('INITIALIZING');
    setProgressPercent(15);
    await performReadinessSequence();
  };

  const skipToDegraded = () => {
    markEstablished();
    setReadinessState('DEGRADED');
    setProgressPercent(100);
  };

  const msgs = STATUS_MESSAGES[readinessState] || ['Preparing your experience...'];
  const currentStatusMessage = msgs[messageIndex % msgs.length];
  const isReadyOrDegraded = readinessState === 'READY' || readinessState === 'DEGRADED';

  return (
    <ReadinessContext.Provider
      value={{
        readinessState,
        readinessDetails,
        progressPercent,
        currentStatusMessage,
        isReadyOrDegraded,
        retryReadiness,
        skipToDegraded,
      }}
    >
      {children}
    </ReadinessContext.Provider>
  );
};

export const useReadiness = (): ReadinessContextType => {
  const context = useContext(ReadinessContext);
  if (!context) {
    throw new Error('useReadiness must be used within a ReadinessProvider');
  }
  return context;
};

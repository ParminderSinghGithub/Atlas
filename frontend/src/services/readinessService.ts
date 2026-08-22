import api from './api';

export interface ServiceHealth {
  name?: string;
  status: 'ready' | 'warming_up' | 'degraded' | 'unavailable';
  latency_ms?: number;
  critical?: boolean;
  error?: string;
}

export interface ReadinessResponse {
  status: 'ready' | 'warming_up' | 'degraded' | 'unavailable';
  timestamp: string;
  summary: {
    total: number;
    ready: number;
    warming: number;
    unavailable: number;
  };
  services: Record<string, ServiceHealth>;
}

class ReadinessService {
  /**
   * Pre-wake sleeping Render services directly from the client browser.
   * Best-effort trigger to initiate cold-start container boot before
   * entering authoritative API Gateway readiness polling.
   */
  async triggerDirectWakeup(): Promise<void> {
    const catalogBase = import.meta.env.VITE_CATALOG_SERVICE_URL || 'https://catalog-service-uo46.onrender.com';
    const userBase = import.meta.env.VITE_USER_SERVICE_URL || 'https://user-service-rzbt.onrender.com';
    const recBase = import.meta.env.VITE_RECOMMENDATION_SERVICE_URL || 'https://recommendation-service-8ag0.onrender.com';

    const targets = [
      `${catalogBase.replace(/\/$/, '')}/api/v1/catalog/health`,
      `${userBase.replace(/\/$/, '')}/api/auth/ping`,
      `${recBase.replace(/\/$/, '')}/health`,
    ];

    // Fire non-blocking requests in parallel from browser with 3s timeout
    await Promise.allSettled(
      targets.map(async (url) => {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 3000);
          await fetch(url, {
            method: 'GET',
            mode: 'no-cors',
            cache: 'no-store',
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
        } catch {
          // Ignore transient errors - this is purely a wake-up trigger
        }
      })
    );
  }

  async checkReadiness(forceRefresh = false): Promise<ReadinessResponse> {
    const response = await api.get<ReadinessResponse>('/v1/ready', {
      params: forceRefresh ? { force_refresh: true } : {},
      timeout: 60000,
    });
    return response.data;
  }
}

export const readinessService = new ReadinessService();

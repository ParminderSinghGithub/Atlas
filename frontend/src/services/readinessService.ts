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
  async checkReadiness(forceRefresh = false): Promise<ReadinessResponse> {
    const response = await api.get<ReadinessResponse>('/v1/ready', {
      params: forceRefresh ? { force_refresh: true } : {},
      timeout: 60000,
    });
    return response.data;
  }
}

export const readinessService = new ReadinessService();

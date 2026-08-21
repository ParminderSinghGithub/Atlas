import api from './api';

export interface Recommendation {
  product_id: string;
  score: number;
  rank: number;
  name?: string;
  price?: number | string;  // Backend returns as string
  category_name?: string;
  category_slug?: string;
  image_url?: string;
  thumbnail_url?: string;
  reason?: string;
  session_boosted?: boolean;
}

export interface RecommendationSessionReranking {
  session_reranking_applied?: boolean;
  categories_matched?: string[];
  products_referenced?: number;
  items_boosted?: number;
  max_boost_applied?: number;
}

export interface RecommendationResponse {
  recommendations: Recommendation[];
  strategy_used: string;
  total_candidates: number;
  total_returned: number;
  session_reranking?: RecommendationSessionReranking | null;
}

class RecommendationService {
  async getRecommendationsForUser(
    userId?: string | null,
    k: number = 10
  ): Promise<RecommendationResponse> {
    try {
      const params: Record<string, string | number> = { k };
      if (userId) {
        params.user_id = userId;
      }
      const response = await api.get('/v1/recommendations', { params });
      
      console.log(`[RECS] User ${userId || 'guest'} recommendations:`, response.data);
      return response.data;
    } catch (error) {
      console.error('[RECS] Failed to fetch recommendations:', error);
      return {
        recommendations: [],
        strategy_used: 'error',
        total_candidates: 0,
        total_returned: 0,
      };
    }
  }

  async getSimilarProducts(
    productId: string,
    k: number = 5
  ): Promise<RecommendationResponse> {
    try {
      const response = await api.get('/v1/recommendations', {
        params: { product_id: productId, k },
      });
      
      console.log(`[RECS] Similar to ${productId}:`, response.data);
      return response.data;
    } catch (error) {
      console.error('[RECS] Failed to fetch similar products:', error);
      return {
        recommendations: [],
        strategy_used: 'error',
        total_candidates: 0,
        total_returned: 0,
      };
    }
  }
}

export const recommendationService = new RecommendationService();

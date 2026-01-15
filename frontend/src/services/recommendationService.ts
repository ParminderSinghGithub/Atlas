import api from './api';

export interface Recommendation {
  product_id: string;
  score: number;
  rank: number;
  name?: string;
  price?: number | string;  // Backend returns as string
  category_name?: string;
  image_url?: string;
  thumbnail_url?: string;
}

export interface RecommendationResponse {
  recommendations: Recommendation[];
  strategy_used: string;
  total_candidates: number;
  total_returned: number;
}

class RecommendationService {
  async getRecommendationsForUser(
    userId: string,
    k: number = 10
  ): Promise<RecommendationResponse> {
    try {
      const response = await api.get('/v1/recommendations', {
        params: { user_id: userId, k },
      });
      
      console.log(`[RECS] User ${userId} recommendations:`, response.data);
      return response.data;
    } catch (error) {
      console.error('[RECS] Failed to fetch user recommendations:', error);
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

import api from './api';

/**
 * Session Tracking Service
 * 
 * Tracks user session signals for intent-aware recommendation re-ranking.
 * 
 * Events:
 * - category_view: User browsing a category
 * - product_view: User viewing a product
 * 
 * These signals are used by the backend's session re-ranker to apply
 * lightweight boosts (+0.1 to +0.3) to recommendations matching session intent.
 */

interface SessionTrackResponse {
  success: boolean;
  message: string;
}

class SessionService {
  /**
   * Track category view for session-aware re-ranking.
   * 
   * @param userId User identifier
   * @param categorySlug Category slug or ID
   */
  async trackCategoryView(userId: string, categorySlug: string): Promise<void> {
    try {
      const response = await api.post<SessionTrackResponse>('/v1/session/track', {
        user_id: userId,
        event_type: 'category_view',
        category_slug: categorySlug,
      });

      console.log(`[SESSION] Tracked category view: ${categorySlug}`, response.data);
    } catch (error) {
      console.error('[SESSION] Failed to track category view:', error);
      // Fail silently - session tracking is optional enhancement
    }
  }

  /**
   * Track product view for session-aware re-ranking.
   * 
   * Note: This is different from event tracking (which goes to Kafka).
   * This is specifically for the session re-ranker.
   * 
   * @param userId User identifier
   * @param productId Product UUID
   */
  async trackProductView(userId: string, productId: string): Promise<void> {
    try {
      const response = await api.post<SessionTrackResponse>('/v1/session/track', {
        user_id: userId,
        event_type: 'product_view',
        product_id: productId,
      });

      console.log(`[SESSION] Tracked product view: ${productId}`, response.data);
    } catch (error) {
      console.error('[SESSION] Failed to track product view:', error);
      // Fail silently - session tracking is optional enhancement
    }
  }
}

export const sessionService = new SessionService();

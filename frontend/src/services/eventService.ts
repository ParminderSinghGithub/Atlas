import api from './api';

// Generate session ID once per browser session
const SESSION_ID = `session-${Date.now()}-${Math.random().toString(36).substring(7)}`;

export type EventType = 'view' | 'add_to_cart' | 'purchase';

interface EventPayload {
  event_type: EventType;
  user_id: string;
  product_id: string;
  timestamp?: string;
  session_id?: string;
}

class EventService {
  private sessionId: string;

  constructor() {
    this.sessionId = SESSION_ID;
  }

  async trackEvent(
    eventType: EventType,
    userId: string,
    productId: string
  ): Promise<void> {
    try {
      const payload: EventPayload = {
        event_type: eventType,
        user_id: userId,
        product_id: productId,
        timestamp: new Date().toISOString(),
        session_id: this.sessionId,
      };

      console.log(`[EVENT] Tracking ${eventType}:`, payload);
      
      const response = await api.post('/events', payload);
      console.log(`[EVENT] Success:`, response.data);
    } catch (error) {
      console.error(`[EVENT] Failed to track ${eventType}:`, error);
      // Don't throw - events should fail silently to not disrupt UX
    }
  }

  trackView(userId: string, productId: string) {
    return this.trackEvent('view', userId, productId);
  }

  trackAddToCart(userId: string, productId: string) {
    return this.trackEvent('add_to_cart', userId, productId);
  }

  trackPurchase(userId: string, productId: string) {
    return this.trackEvent('purchase', userId, productId);
  }
}

export const eventService = new EventService();

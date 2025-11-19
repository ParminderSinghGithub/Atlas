-- =====================================================
-- Event Logs Table Migration
-- =====================================================
-- This table stores all user events consumed from Kafka
-- Used for analytics, reporting, and event replay
-- =====================================================

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id TEXT,
    session_id TEXT NOT NULL,
    product_id TEXT,
    properties JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ NOT NULL
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_product_id ON events(product_id) WHERE product_id IS NOT NULL;

-- Create index for JSONB properties (GIN index for efficient JSONB queries)
CREATE INDEX IF NOT EXISTS idx_events_properties ON events USING GIN (properties);

-- Add comments for documentation
COMMENT ON TABLE events IS 'Stores all user events from Kafka topic user_events';
COMMENT ON COLUMN events.event_id IS 'Unique identifier for the event (UUID)';
COMMENT ON COLUMN events.event_type IS 'Type of event: view, click, add_to_cart, purchase';
COMMENT ON COLUMN events.user_id IS 'User identifier (optional, null for anonymous users)';
COMMENT ON COLUMN events.session_id IS 'Session identifier for tracking user sessions';
COMMENT ON COLUMN events.product_id IS 'Product identifier (optional, for product-related events)';
COMMENT ON COLUMN events.properties IS 'Additional event properties stored as JSONB';
COMMENT ON COLUMN events.ts IS 'Event timestamp in UTC';

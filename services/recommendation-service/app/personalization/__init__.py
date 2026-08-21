"""
Long-Term User Personalization Module.

Provides persistent user preference signals derived from the PostgreSQL
events table (catalog service) to inform recommendation ranking.

Distinct from session reranking (Redis, 30-min TTL):
    - Long-term: historical events from PostgreSQL (permanent, cached 1h in Redis)
    - Session: current-visit signals from Redis (ephemeral, 30-min TTL)
"""

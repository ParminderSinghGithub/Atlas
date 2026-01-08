#!/usr/bin/env python3
"""
Offline Metrics Aggregation for Atlas Recommendation System

Purpose:
    Compute operational metrics from recommendation logs without requiring
    heavy observability infrastructure (Prometheus, Datadog, etc.)

Metrics Computed:
    - Impression count (total recommendations served)
    - Unique items recommended (catalog coverage)
    - Popularity fallback rate (model health indicator)
    - Per-strategy usage % (A/B testing insights)
    - Latency statistics (p50, p95, p99)

Input:
    Docker container logs or structured log files containing RECOMMENDATION_EVENT entries

Output:
    JSON summary with key metrics for operational monitoring

Usage:
    # From Docker logs
    docker logs infra-recommendation-service-1 2>&1 | python monitoring/aggregate_metrics.py
    
    # From log files
    cat logs/recommendation-service.log | python monitoring/aggregate_metrics.py
    
    # Save to file
    docker logs infra-recommendation-service-1 2>&1 | python monitoring/aggregate_metrics.py > metrics_report.json

Why This Approach:
    - No additional infrastructure (Prometheus, Grafana, Datadog)
    - Works with standard Docker logs
    - Offline analysis (doesn't impact serving)
    - Fresher-level implementation
    - Production-realistic for low-traffic platforms
"""

import sys
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Any
import statistics


def parse_log_line(line: str) -> Dict[str, Any]:
    """
    Parse a log line and extract JSON recommendation event.
    
    Expected format:
        2026-01-08 21:30:45 | INFO     | app.api.routes | RECOMMENDATION_EVENT: {...}
    
    Returns:
        Parsed JSON dict or None if not a recommendation event
    """
    # Look for RECOMMENDATION_EVENT marker
    if "RECOMMENDATION_EVENT:" not in line:
        return None
    
    try:
        # Extract JSON portion after marker
        json_start = line.index("RECOMMENDATION_EVENT:") + len("RECOMMENDATION_EVENT:")
        json_str = line[json_start:].strip()
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Warning: Failed to parse log line: {e}", file=sys.stderr)
        return None


def aggregate_metrics(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute operational metrics from recommendation events.
    
    Metrics:
        - total_impressions: Number of recommendation requests
        - unique_users: Number of distinct users served
        - unique_items_recommended: Catalog coverage
        - strategy_breakdown: % of requests per strategy
        - fallback_rate: % using popularity fallback
        - latency_stats: p50, p95, p99 serving latency
        - avg_recommendations_per_request: Mean k value
    """
    if not events:
        return {
            "error": "No recommendation events found in logs",
            "total_impressions": 0
        }
    
    # Counters
    total_impressions = len(events)
    unique_users = set()
    unique_items = set()
    strategy_counts = Counter()
    latencies = []
    num_recommendations = []
    
    for event in events:
        # User tracking (hashed for privacy)
        if event.get("user_id_hash"):
            unique_users.add(event["user_id_hash"])
        
        # Item coverage
        for item_id in event.get("recommended_items", []):
            unique_items.add(item_id)
        
        # Strategy tracking
        strategy = event.get("strategy", "unknown")
        strategy_counts[strategy] += 1
        
        # Latency tracking
        if "latency_ms" in event:
            latencies.append(event["latency_ms"])
        
        # Recommendations count
        if "num_recommendations" in event:
            num_recommendations.append(event["num_recommendations"])
    
    # Compute percentiles
    latencies.sort()
    latency_stats = {}
    if latencies:
        latency_stats = {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(latencies[int(0.95 * len(latencies))], 2) if len(latencies) > 1 else latencies[0],
            "p99": round(latencies[int(0.99 * len(latencies))], 2) if len(latencies) > 1 else latencies[0],
            "mean": round(statistics.mean(latencies), 2),
            "max": round(max(latencies), 2)
        }
    
    # Strategy breakdown (percentages)
    strategy_breakdown = {
        strategy: {
            "count": count,
            "percentage": round(100 * count / total_impressions, 2)
        }
        for strategy, count in strategy_counts.most_common()
    }
    
    # Fallback rate (popularity = fallback)
    fallback_strategies = ["popularity", "popularity_fallback"]
    fallback_count = sum(count for strategy, count in strategy_counts.items() if strategy in fallback_strategies)
    fallback_rate = round(100 * fallback_count / total_impressions, 2)
    
    # Average recommendations per request
    avg_k = round(statistics.mean(num_recommendations), 2) if num_recommendations else 0
    
    return {
        "summary": {
            "total_impressions": total_impressions,
            "unique_users": len(unique_users),
            "unique_items_recommended": len(unique_items),
            "catalog_coverage_pct": round(100 * len(unique_items) / 2000, 2) if len(unique_items) > 0 else 0,  # Assuming ~2000 products
            "fallback_rate_pct": fallback_rate,
            "avg_recommendations_per_request": avg_k
        },
        "strategy_breakdown": strategy_breakdown,
        "latency_stats_ms": latency_stats,
        "health_indicators": {
            "high_fallback_rate": fallback_rate > 50,  # More than 50% fallbacks indicates model issues
            "low_coverage": len(unique_items) < 100,  # Less than 100 unique items = poor diversity
            "high_latency": latency_stats.get("p95", 0) > 500  # p95 > 500ms = slow
        }
    }


def main():
    """
    Read logs from stdin and compute metrics.
    """
    print("Reading recommendation logs from stdin...", file=sys.stderr)
    
    events = []
    line_count = 0
    
    for line in sys.stdin:
        line_count += 1
        event = parse_log_line(line)
        if event:
            events.append(event)
    
    print(f"Processed {line_count} log lines, found {len(events)} recommendation events", file=sys.stderr)
    
    # Compute metrics
    metrics = aggregate_metrics(events)
    
    # Add metadata
    metrics["metadata"] = {
        "generated_at": datetime.utcnow().isoformat(),
        "log_lines_processed": line_count,
        "events_parsed": len(events)
    }
    
    # Output JSON
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

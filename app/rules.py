"""Deterministic rules shared by agents (kept in one place so they are easy to explain)."""
import re

CATEGORIES = ["bad_deployment", "db_pool_exhaustion", "cache_degradation",
              "upstream_dependency", "certificate_expiry"]

# Order matters: first match wins (specific patterns before generic ones).
LOG_RULES = [
    ("certificate_expiry", r"certificate|x509|ssl handshake|tls alert"),
    ("db_pool_exhaustion", r"connection pool|pool exhausted|connection is not available|too many connections|hikari"),
    ("cache_degradation", r"redis|oom command not allowed|evict|maxmemory"),
    ("upstream_dependency", r"upstream|read timed out|gateway timeout|circuit breaker"),
    ("bad_deployment", r"nullpointer|exception|traceback|stack trace"),
]

# metric -> (comparator, threshold, category or None for generic symptoms)
HEALTH_RULES = {
    "db_pool_utilization_pct": ("gt", 90, "db_pool_exhaustion"),
    "redis_memory_pct": ("gt", 85, "cache_degradation"),
    "redis_p99_ms": ("gt", 50, "cache_degradation"),
    "upstream_latency_ms": ("gt", 2000, "upstream_dependency"),
    "cert_days_remaining": ("lt", 1, "certificate_expiry"),
    "pod_restarts": ("gt", 3, "bad_deployment"),
    "error_rate_pct": ("gt", 5, None),
    "p95_latency_ms": ("gt", 1000, None),
    "cpu_pct": ("gt", 85, None),
    "memory_pct": ("gt", 90, None),
}


def classify_log_line(message: str):
    text = message.lower()
    for category, pattern in LOG_RULES:
        if re.search(pattern, text):
            return category
    return None


def normalize_signature(message: str) -> str:
    """Collapse numbers/ids so repeated errors group together."""
    return re.sub(r"\d+", "<n>", message)


def is_breached(value, comparator, threshold) -> bool:
    return value > threshold if comparator == "gt" else value < threshold


def severity(value, comparator, threshold) -> float:
    """0..1 overshoot of a breached threshold."""
    base = abs(threshold) if threshold else 1
    over = (value - threshold) if comparator == "gt" else (threshold - value)
    return max(0.0, min(1.0, over / base))

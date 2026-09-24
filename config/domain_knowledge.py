"""
Incident Ops domain knowledge — injected into agent prompts to provide
context about the engineering environment, severity definitions, on-call
rotations, and common services.

Usage:
    from config.domain_knowledge import get_domain_context, ON_CALL_ROSTER, SEVERITY_DEFINITIONS
"""

from typing import Optional

# ------------------------------------------------------------------ #
# Severity definitions                                                  #
# ------------------------------------------------------------------ #

SEVERITY_DEFINITIONS = {
    "P0": {
        "label": "Critical",
        "criteria": (
            "Customer-facing service fully unavailable with no workaround. "
            "Affects core business transactions (payments, login, checkout). "
            "Multi-region or full data-plane impact."
        ),
        "response_sla": "Immediate — bridge within 5 minutes, exec notification within 15 minutes",
        "examples": [
            "Payment gateway down, all transactions failing",
            "Auth service returning 500 for all login attempts",
            "Checkout service error rate > 50% with no fallback",
        ],
    },
    "P1": {
        "label": "High",
        "criteria": (
            "Significant service degradation with workaround available, or single-region impact. "
            "Non-critical path affected, or error rate elevated but below 50%."
        ),
        "response_sla": "Acknowledge within 15 minutes, mitigation plan within 30 minutes",
        "examples": [
            "Redis memory > 85%, checkout latency elevated but functional",
            "Lambda timeouts in one region, traffic shifted to secondary",
            "DB connection pool exhaustion, retries succeeding",
        ],
    },
    "P2": {
        "label": "Medium",
        "criteria": (
            "Non-production environment affected, or known flaky alert with no user impact. "
            "Capacity warning with sufficient runway."
        ),
        "response_sla": "Acknowledge within 1 hour, schedule fix within 24 hours",
        "examples": [
            "Staging environment deployment failure",
            "Disk usage > 70% on non-critical host",
            "Periodic false-positive alert (known issue, tracked in backlog)",
        ],
    },
    "P3": {
        "label": "Low",
        "criteria": "Cosmetic, informational, or long-term hygiene items.",
        "response_sla": "Track in backlog, fix in next sprint",
        "examples": [
            "Log rotation job missed once",
            "Deprecated API version still receiving <1% traffic",
        ],
    },
}

# ------------------------------------------------------------------ #
# On-call roster (mock — replace with PagerDuty API in production)    #
# ------------------------------------------------------------------ #

ON_CALL_ROSTER = {
    "platform-sre": {
        "team": "Platform SRE",
        "description": "Infrastructure, Kubernetes, networking, storage",
        "primary": "Alice Chen",
        "secondary": "Bob Martinez",
        "escalation_path": "platform-sre → VP Engineering",
        "slack_channel": "#platform-incidents",
        "services": ["checkout-service", "payment-gateway", "redis-cache", "postgres-primary"],
    },
    "payments-eng": {
        "team": "Payments Engineering",
        "description": "Payment processing, fraud detection, transaction ledger",
        "primary": "Carol Singh",
        "secondary": "David Kim",
        "escalation_path": "payments-eng → Payments Director",
        "slack_channel": "#payments-incidents",
        "services": ["payment-gateway", "fraud-service", "ledger-service"],
    },
    "auth-eng": {
        "team": "Auth & Identity Engineering",
        "description": "Authentication, authorization, session management",
        "primary": "Eva Zhao",
        "secondary": "Frank Okafor",
        "escalation_path": "auth-eng → Security Lead",
        "slack_channel": "#auth-incidents",
        "services": ["auth-service", "session-store", "oauth-proxy"],
    },
    "data-eng": {
        "team": "Data Engineering",
        "description": "Data pipelines, analytics, warehouse",
        "primary": "Grace Liu",
        "secondary": "Henry Park",
        "escalation_path": "data-eng → Data Platform Lead",
        "slack_channel": "#data-incidents",
        "services": ["kafka-broker", "spark-jobs", "data-warehouse"],
    },
}

# ------------------------------------------------------------------ #
# Service catalogue                                                     #
# ------------------------------------------------------------------ #

SERVICE_CATALOGUE = {
    "checkout-service": {
        "owner": "platform-sre",
        "tier": "T1",
        "description": "Core checkout flow — cart, order creation, payment orchestration",
        "slo_availability": "99.99%",
        "key_dependencies": ["payment-gateway", "redis-cache", "postgres-primary"],
        "runbook_tags": ["checkout", "order", "cart"],
    },
    "payment-gateway": {
        "owner": "payments-eng",
        "tier": "T1",
        "description": "External payment processor integration and retry logic",
        "slo_availability": "99.95%",
        "key_dependencies": ["fraud-service", "ledger-service"],
        "runbook_tags": ["payment", "gateway", "transaction"],
    },
    "auth-service": {
        "owner": "auth-eng",
        "tier": "T1",
        "description": "User authentication, JWT issuance, OAuth flows",
        "slo_availability": "99.99%",
        "key_dependencies": ["session-store", "postgres-primary"],
        "runbook_tags": ["auth", "login", "session", "token"],
    },
    "redis-cache": {
        "owner": "platform-sre",
        "tier": "T2",
        "description": "In-memory cache for sessions, rate limiting, and ephemeral state",
        "slo_availability": "99.9%",
        "key_dependencies": [],
        "runbook_tags": ["redis", "cache", "memory", "oom"],
    },
    "lambda-processor": {
        "owner": "platform-sre",
        "tier": "T2",
        "description": "Event-driven async processing (notifications, webhooks, batch jobs)",
        "slo_availability": "99.5%",
        "key_dependencies": ["kafka-broker"],
        "runbook_tags": ["lambda", "timeout", "async", "event"],
    },
    "postgres-primary": {
        "owner": "platform-sre",
        "tier": "T1",
        "description": "Primary relational database for transactional data",
        "slo_availability": "99.99%",
        "key_dependencies": [],
        "runbook_tags": ["postgres", "db", "database", "connection", "replication"],
    },
}

# ------------------------------------------------------------------ #
# Monitoring tools                                                      #
# ------------------------------------------------------------------ #

MONITORING_TOOLS = {
    "Datadog":    "Primary metrics, APM traces, and log aggregation",
    "PagerDuty":  "On-call alerting and escalation policy enforcement",
    "Grafana":    "Infrastructure dashboards and SLO burn-rate charts",
    "CloudWatch": "AWS-native metrics for Lambda, RDS, and managed services",
}

# ------------------------------------------------------------------ #
# Domain context string builder                                         #
# ------------------------------------------------------------------ #

def get_domain_context(include_roster: bool = True, service: Optional[str] = None) -> str:
    """
    Build a domain context string for injection into agent prompts.

    Args:
        include_roster: Whether to include on-call roster details.
        service: If provided, include service-specific context.

    Returns:
        Formatted context string.
    """
    lines = [
        "=== Incident Ops Domain Context ===",
        "",
        "SEVERITY DEFINITIONS:",
    ]
    for level, info in SEVERITY_DEFINITIONS.items():
        lines.append(f"  {level} ({info['label']}): {info['criteria']}")
        lines.append(f"    SLA: {info['response_sla']}")

    lines += ["", "MONITORING TOOLS:"]
    for tool, desc in MONITORING_TOOLS.items():
        lines.append(f"  {tool}: {desc}")

    if include_roster:
        lines += ["", "ON-CALL ROTATIONS:"]
        for key, rotation in ON_CALL_ROSTER.items():
            lines.append(
                f"  {rotation['team']} ({key}): primary={rotation['primary']}, "
                f"secondary={rotation['secondary']}, channel={rotation['slack_channel']}"
            )
            lines.append(f"    Services: {', '.join(rotation['services'])}")

    if service and service in SERVICE_CATALOGUE:
        svc = SERVICE_CATALOGUE[service]
        lines += [
            "",
            f"SERVICE CONTEXT — {service}:",
            f"  Owner: {svc['owner']} | Tier: {svc['tier']} | SLO: {svc['slo_availability']}",
            f"  Description: {svc['description']}",
            f"  Dependencies: {', '.join(svc['key_dependencies']) or 'none'}",
        ]

    lines.append("")
    return "\n".join(lines)


def get_oncall_for_service(service_name: str) -> Optional[dict]:
    """Return the on-call rotation responsible for a given service."""
    svc = SERVICE_CATALOGUE.get(service_name)
    if not svc:
        return None
    return ON_CALL_ROSTER.get(svc["owner"])


def get_severity_guide() -> str:
    """Return a compact severity decision guide for use in triage prompts."""
    lines = ["Severity guide:"]
    for level, info in SEVERITY_DEFINITIONS.items():
        lines.append(f"  {level}: {info['criteria']}")
    return "\n".join(lines)

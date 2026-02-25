# Observability Setup Guide

This guide explains how to set up and use the new observability features: structured logging, metrics, and health checks.

## Quick Start

### 1. Install Dependencies

```bash
pip install -e .
# Or using uv
uv pip install -e .
```

This will install:
- `prometheus-client` - For metrics collection
- `structlog` - For structured logging

### 2. Configure Structured Logging

Add to your agent initialization:

```python
import structlog
import logging

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()  # Or use ConsoleRenderer() for development
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Standard logging configuration
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)
```

### 3. Expose Metrics Endpoint

Add Prometheus metrics endpoint to your agent server:

```python
from prometheus_client import start_http_server, generate_latest
from aiohttp import web

# Start metrics server (runs on port 8000 by default)
start_http_server(8000)

# Or expose via HTTP endpoint
async def metrics_handler(request):
    return web.Response(
        body=generate_latest(),
        content_type='text/plain; version=0.0.4; charset=utf-8'
    )

app = web.Application()
app.router.add_get('/metrics', metrics_handler)
```

### 4. Initialize Health Checks

```python
from livekit_voice_agent.health_checks import get_health_checker

# Get health checker
health_checker = get_health_checker()

# Define health check functions for services
async def check_openai_health():
    # Lightweight check - e.g., verify API key is valid
    import openai
    client = openai.OpenAI()
    # Simple validation check
    pass

async def check_deepgram_health():
    # Check Deepgram service health
    pass

# Start periodic health checks
services = {
    "openai_llm": check_openai_health,
    "deepgram_stt": check_deepgram_health,
    "elevenlabs_tts": None,  # Use default ping check
}

await health_checker.start_periodic_checks(services)
```

## Features

### Structured Logging

All logs are now structured with context:

```json
{
  "event": "operation_succeeded",
  "service": "openai_llm",
  "operation": "generate",
  "attempts": 2,
  "duration": 1.234,
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

Benefits:
- Easy to parse and search
- Better integration with log aggregation tools (ELK, Datadog, etc.)
- Consistent format across all logs

### Metrics

Available metrics:

**Operation Metrics:**
- `operation_attempts_total` - Total operation attempts
- `operation_duration_seconds` - Operation duration histogram
- `operation_success_total` - Successful operations
- `operation_failure_total` - Failed operations (by error category)

**Retry Metrics:**
- `retry_attempts_total` - Retry attempts
- `retry_delay_seconds` - Delay between retries

**Circuit Breaker Metrics:**
- `circuit_breaker_state` - Current state (0=closed, 1=half-open, 2=open)
- `circuit_breaker_failures_total` - Total failures
- `circuit_breaker_successes_total` - Total successes
- `circuit_breaker_state_changes_total` - State transitions

**Fallback & Escalation:**
- `fallback_usage_total` - Fallback service usage
- `escalation_events_total` - Escalation events

**Health Metrics:**
- `service_health_score` - Health score (0.0-1.0)
- `service_health_check_duration_seconds` - Health check duration

### Health Checks

Health checks provide:
- **Proactive Monitoring** - Detect issues before they cause failures
- **Health Scoring** - 0.0 to 1.0 score based on:
  - Recent success rate (40%)
  - Average response time (30%)
  - Consistency (30%)
- **Circuit Breaker Bypass** - Automatically bypass circuit breaker if health checks show recovery

## Example Queries

### Prometheus Queries

**Success Rate:**
```promql
rate(operation_success_total[5m]) / rate(operation_attempts_total[5m])
```

**Error Rate by Category:**
```promql
sum(rate(operation_failure_total[5m])) by (error_category)
```

**Circuit Breaker State:**
```promql
circuit_breaker_state
```

**P95 Latency:**
```promql
histogram_quantile(0.95, operation_duration_seconds_bucket)
```

**Service Health:**
```promql
service_health_score
```

## Integration with Monitoring Tools

### Grafana Dashboard

Create dashboards showing:
- Operation success/failure rates
- Latency percentiles (p50, p95, p99)
- Circuit breaker states
- Service health scores
- Retry patterns

### Alerting Rules

Example Prometheus alerting rules:

```yaml
groups:
  - name: service_health
    rules:
      - alert: ServiceUnhealthy
        expr: service_health_score < 0.5
        for: 5m
        annotations:
          summary: "Service {{ $labels.service }} is unhealthy"
      
      - alert: HighErrorRate
        expr: rate(operation_failure_total[5m]) > 0.1
        for: 5m
        annotations:
          summary: "High error rate for {{ $labels.service }}"
      
      - alert: CircuitBreakerOpen
        expr: circuit_breaker_state == 2
        for: 2m
        annotations:
          summary: "Circuit breaker open for {{ $labels.service }}"
```

## Best Practices

1. **Log Levels:**
   - `DEBUG` - Detailed debugging info
   - `INFO` - Normal operations (successes, state changes)
   - `WARNING` - Retries, fallbacks, degraded states
   - `ERROR` - Failures, escalations

2. **Metrics Labels:**
   - Keep label cardinality low (avoid high-cardinality labels like user IDs)
   - Use consistent label names across metrics

3. **Health Checks:**
   - Keep health checks lightweight (< 1 second)
   - Don't perform expensive operations in health checks
   - Use health checks to inform circuit breaker decisions

4. **Monitoring:**
   - Set up dashboards for key metrics
   - Configure alerts for critical failures
   - Review metrics regularly to optimize retry strategies

## Troubleshooting

### Metrics Not Appearing

1. Check if Prometheus client is installed: `pip list | grep prometheus`
2. Verify metrics endpoint is accessible: `curl http://localhost:8000/metrics`
3. Check logs for import errors

### Structured Logs Not Working

1. Verify structlog is installed: `pip list | grep structlog`
2. Check structlog configuration
3. Fallback to standard logging if structlog unavailable (automatic)

### Health Checks Not Running

1. Verify health checker is initialized
2. Check if periodic checks are started
3. Review logs for health check errors

## Next Steps

- Set up Grafana dashboards
- Configure alerting rules
- Integrate with your monitoring stack (Datadog, New Relic, etc.)
- Review metrics to optimize retry strategies
- Use health scores to inform circuit breaker decisions


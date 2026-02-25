"""
Metrics collection for failure-tolerant execution system.

Provides Prometheus metrics for monitoring operations, failures, circuit breakers,
and system health.
"""

import time
from typing import Optional
from functools import wraps

try:
    from prometheus_client import Counter, Histogram, Gauge, Info
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Create dummy classes if prometheus_client not available
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Info:
        def __init__(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self


# Operation metrics
operation_attempts_total = Counter(
    'operation_attempts_total',
    'Total number of operation attempts',
    ['service', 'operation', 'attempt_number']
) if PROMETHEUS_AVAILABLE else Counter()

operation_duration_seconds = Histogram(
    'operation_duration_seconds',
    'Duration of operations in seconds',
    ['service', 'operation', 'status'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
) if PROMETHEUS_AVAILABLE else Histogram()

operation_success_total = Counter(
    'operation_success_total',
    'Total number of successful operations',
    ['service', 'operation']
) if PROMETHEUS_AVAILABLE else Counter()

operation_failure_total = Counter(
    'operation_failure_total',
    'Total number of failed operations',
    ['service', 'operation', 'error_category']
) if PROMETHEUS_AVAILABLE else Counter()

# Retry metrics
retry_attempts_total = Counter(
    'retry_attempts_total',
    'Total number of retry attempts',
    ['service', 'operation', 'attempt_number']
) if PROMETHEUS_AVAILABLE else Counter()

retry_delay_seconds = Histogram(
    'retry_delay_seconds',
    'Delay between retry attempts in seconds',
    ['service', 'operation'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
) if PROMETHEUS_AVAILABLE else Histogram()

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    'circuit_breaker_state',
    'Current state of circuit breaker (0=closed, 1=half-open, 2=open)',
    ['service']
) if PROMETHEUS_AVAILABLE else Gauge()

circuit_breaker_failures_total = Counter(
    'circuit_breaker_failures_total',
    'Total number of failures recorded by circuit breaker',
    ['service']
) if PROMETHEUS_AVAILABLE else Counter()

circuit_breaker_successes_total = Counter(
    'circuit_breaker_successes_total',
    'Total number of successes recorded by circuit breaker',
    ['service']
) if PROMETHEUS_AVAILABLE else Counter()

circuit_breaker_state_changes_total = Counter(
    'circuit_breaker_state_changes_total',
    'Total number of circuit breaker state changes',
    ['service', 'from_state', 'to_state']
) if PROMETHEUS_AVAILABLE else Counter()

# Fallback metrics
fallback_usage_total = Counter(
    'fallback_usage_total',
    'Total number of fallback service usages',
    ['service', 'operation', 'fallback_type']
) if PROMETHEUS_AVAILABLE else Counter()

# Escalation metrics
escalation_events_total = Counter(
    'escalation_events_total',
    'Total number of escalation events',
    ['service', 'operation', 'escalation_level']
) if PROMETHEUS_AVAILABLE else Counter()

# Health metrics
service_health_score = Gauge(
    'service_health_score',
    'Health score of service (0.0 to 1.0)',
    ['service']
) if PROMETHEUS_AVAILABLE else Gauge()

service_health_check_duration_seconds = Histogram(
    'service_health_check_duration_seconds',
    'Duration of health checks in seconds',
    ['service', 'status'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
) if PROMETHEUS_AVAILABLE else Histogram()

# System info
system_info = Info(
    'system_info',
    'System information'
) if PROMETHEUS_AVAILABLE else Info()


class MetricsCollector:
    """Collects and records metrics for operations."""
    
    @staticmethod
    def record_operation_attempt(
        service: str,
        operation: str,
        attempt_number: int
    ):
        """Record an operation attempt."""
        operation_attempts_total.labels(
            service=service,
            operation=operation,
            attempt_number=str(attempt_number)
        ).inc()
    
    @staticmethod
    def record_operation_duration(
        service: str,
        operation: str,
        duration: float,
        success: bool
    ):
        """Record operation duration."""
        status = 'success' if success else 'failure'
        operation_duration_seconds.labels(
            service=service,
            operation=operation,
            status=status
        ).observe(duration)
    
    @staticmethod
    def record_operation_success(
        service: str,
        operation: str
    ):
        """Record a successful operation."""
        operation_success_total.labels(
            service=service,
            operation=operation
        ).inc()
    
    @staticmethod
    def record_operation_failure(
        service: str,
        operation: str,
        error_category: str
    ):
        """Record a failed operation."""
        operation_failure_total.labels(
            service=service,
            operation=operation,
            error_category=error_category
        ).inc()
    
    @staticmethod
    def record_retry_attempt(
        service: str,
        operation: str,
        attempt_number: int,
        delay: float
    ):
        """Record a retry attempt."""
        retry_attempts_total.labels(
            service=service,
            operation=operation,
            attempt_number=str(attempt_number)
        ).inc()
        
        retry_delay_seconds.labels(
            service=service,
            operation=operation
        ).observe(delay)
    
    @staticmethod
    def record_circuit_breaker_state(
        service: str,
        state: str
    ):
        """Record circuit breaker state."""
        state_value = {'closed': 0, 'half-open': 1, 'open': 2}.get(state, 0)
        circuit_breaker_state.labels(service=service).set(state_value)
    
    @staticmethod
    def record_circuit_breaker_failure(service: str):
        """Record a circuit breaker failure."""
        circuit_breaker_failures_total.labels(service=service).inc()
    
    @staticmethod
    def record_circuit_breaker_success(service: str):
        """Record a circuit breaker success."""
        circuit_breaker_successes_total.labels(service=service).inc()
    
    @staticmethod
    def record_circuit_breaker_state_change(
        service: str,
        from_state: str,
        to_state: str
    ):
        """Record a circuit breaker state change."""
        circuit_breaker_state_changes_total.labels(
            service=service,
            from_state=from_state,
            to_state=to_state
        ).inc()
    
    @staticmethod
    def record_fallback_usage(
        service: str,
        operation: str,
        fallback_type: str
    ):
        """Record fallback service usage."""
        fallback_usage_total.labels(
            service=service,
            operation=operation,
            fallback_type=fallback_type
        ).inc()
    
    @staticmethod
    def record_escalation(
        service: str,
        operation: str,
        escalation_level: str
    ):
        """Record an escalation event."""
        escalation_events_total.labels(
            service=service,
            operation=operation,
            escalation_level=escalation_level
        ).inc()
    
    @staticmethod
    def record_service_health_score(service: str, score: float):
        """Record service health score."""
        service_health_score.labels(service=service).set(score)
    
    @staticmethod
    def record_health_check_duration(
        service: str,
        duration: float,
        healthy: bool
    ):
        """Record health check duration."""
        status = 'healthy' if healthy else 'unhealthy'
        service_health_check_duration_seconds.labels(
            service=service,
            status=status
        ).observe(duration)


def track_operation(service: str, operation: str):
    """Decorator to track operation metrics."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            attempt = 1
            success = False
            
            try:
                MetricsCollector.record_operation_attempt(service, operation, attempt)
                result = await func(*args, **kwargs)
                success = True
                MetricsCollector.record_operation_success(service, operation)
                return result
            except Exception as e:
                # Error category will be recorded by caller
                raise
            finally:
                duration = time.time() - start_time
                MetricsCollector.record_operation_duration(
                    service, operation, duration, success
                )
        
        return wrapper
    return decorator


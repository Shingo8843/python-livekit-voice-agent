"""
Failure-tolerant execution framework with retries, escalation, and uncertainty handling.

This module provides a comprehensive error handling system for the voice agent,
including:
- Error classification (transient vs permanent, service-specific)
- Retry strategies (exponential backoff, circuit breaker)
- Escalation paths (fallback services, human transfer, graceful degradation)
- Uncertainty handling (timeouts, partial failures, degraded modes)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar, Generic
from functools import wraps

import pybreaker
from tenacity import (
    AsyncRetrying,
    stop_after_attempt,
    wait_exponential,
    wait_random,
    retry_if_exception,
    before_sleep_log,
    after_log,
)

# Try to use structlog, fallback to standard logging
try:
    import structlog
    logger = structlog.get_logger(__name__)
    STRUCTLOG_AVAILABLE = True
except ImportError:
    logger = logging.getLogger(__name__)
    STRUCTLOG_AVAILABLE = False

# Import metrics and health checks
try:
    from .metrics import MetricsCollector
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    MetricsCollector = None

try:
    from .health_checks import get_health_checker
    HEALTH_CHECKS_AVAILABLE = True
except ImportError:
    HEALTH_CHECKS_AVAILABLE = False
    get_health_checker = None

T = TypeVar('T')


class ErrorCategory(Enum):
    """Categories of errors for classification and handling."""
    TRANSIENT = "transient"  # Temporary, likely to succeed on retry
    PERMANENT = "permanent"  # Won't succeed on retry
    RATE_LIMIT = "rate_limit"  # Rate limiting, needs backoff
    TIMEOUT = "timeout"  # Operation timed out
    NETWORK = "network"  # Network connectivity issues
    AUTHENTICATION = "authentication"  # Auth failures
    QUOTA_EXCEEDED = "quota_exceeded"  # Service quota exceeded
    SERVICE_UNAVAILABLE = "service_unavailable"  # Service down
    INVALID_INPUT = "invalid_input"  # Bad input, won't succeed on retry


class EscalationLevel(Enum):
    """Levels of escalation for failure handling."""
    RETRY = "retry"  # Simple retry
    RETRY_WITH_BACKOFF = "retry_with_backoff"  # Retry with exponential backoff
    FALLBACK_SERVICE = "fallback_service"  # Use alternative service
    GRACEFUL_DEGRADATION = "graceful_degradation"  # Continue with reduced functionality
    HUMAN_TRANSFER = "human_transfer"  # Transfer to human agent
    ABORT = "abort"  # Abort operation


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd
    retryable_categories: set[ErrorCategory] = field(default_factory=lambda: {
        ErrorCategory.TRANSIENT,
        ErrorCategory.NETWORK,
        ErrorCategory.TIMEOUT,
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.SERVICE_UNAVAILABLE,
    })


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5  # Open circuit after N failures
    success_threshold: int = 1  # Close circuit after N successes (in half-open)
    timeout: int = 60  # Seconds before trying half-open state
    expected_exception: type[Exception] = Exception  # Exception types to count as failures
    listeners: list[pybreaker.CircuitBreakerListener] = field(default_factory=list)


@dataclass
class FailureContext:
    """Context information about a failure."""
    error: Exception
    category: ErrorCategory
    attempt_number: int
    total_attempts: int
    elapsed_time: float
    service_name: str
    operation_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult(Generic[T]):
    """Result of an execution attempt."""
    success: bool
    value: Optional[T] = None
    error: Optional[Exception] = None
    category: Optional[ErrorCategory] = None
    attempts: int = 0
    elapsed_time: float = 0.0
    escalated: bool = False
    escalation_level: Optional[EscalationLevel] = None


class ErrorClassifier:
    """Classifies errors into categories for appropriate handling."""
    
    @staticmethod
    def classify(error: Exception, service_name: str = "") -> ErrorCategory:
        """
        Classify an error into a category.
        
        Args:
            error: The exception that occurred
            service_name: Name of the service that failed (for context)
        
        Returns:
            ErrorCategory classification
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()
        
        # Network-related errors
        if any(keyword in error_msg for keyword in ['connection', 'network', 'timeout', 'unreachable', 'dns']):
            return ErrorCategory.NETWORK
        
        # Timeout errors
        if 'timeout' in error_msg or 'timed out' in error_msg:
            return ErrorCategory.TIMEOUT
        
        # Rate limiting
        if any(keyword in error_msg for keyword in ['rate limit', 'too many requests', '429', 'quota']):
            if 'quota' in error_msg or 'quota exceeded' in error_msg:
                return ErrorCategory.QUOTA_EXCEEDED
            return ErrorCategory.RATE_LIMIT
        
        # Authentication errors
        if any(keyword in error_msg for keyword in ['auth', 'unauthorized', '401', '403', 'invalid key', 'api key']):
            return ErrorCategory.AUTHENTICATION
        
        # Service unavailable
        if any(keyword in error_msg for keyword in ['503', 'service unavailable', 'unavailable', 'down', 'maintenance']):
            return ErrorCategory.SERVICE_UNAVAILABLE
        
        # Invalid input (usually permanent)
        if any(keyword in error_msg for keyword in ['invalid', 'bad request', '400', 'malformed', 'validation']):
            return ErrorCategory.INVALID_INPUT
        
        # OpenAI-specific errors
        if 'openai' in service_name.lower():
            if '429' in error_msg:
                return ErrorCategory.RATE_LIMIT
            if '401' in error_msg or '403' in error_msg:
                return ErrorCategory.AUTHENTICATION
            if '500' in error_msg or '502' in error_msg or '503' in error_msg:
                return ErrorCategory.SERVICE_UNAVAILABLE
        
        # Deepgram-specific errors
        if 'deepgram' in service_name.lower():
            if '429' in error_msg:
                return ErrorCategory.RATE_LIMIT
            if '401' in error_msg:
                return ErrorCategory.AUTHENTICATION
        
        # Cartesia/ElevenLabs-specific errors
        if any(service in service_name.lower() for service in ['cartesia', 'elevenlabs', 'eleven']):
            if '429' in error_msg:
                return ErrorCategory.RATE_LIMIT
            if '401' in error_msg:
                return ErrorCategory.AUTHENTICATION
        
        # Default: assume transient for unknown errors
        return ErrorCategory.TRANSIENT


class RetryStrategy:
    """Implements retry strategies using tenacity."""
    
    def __init__(self, config: RetryConfig, error_classifier: ErrorClassifier):
        self.config = config
        self.error_classifier = error_classifier
    
    def _should_retry_exception(self, exception: Exception) -> bool:
        """Determine if exception should be retried based on error category."""
        category = self.error_classifier.classify(exception, "")
        return category in self.config.retryable_categories
    
    def build_retry_strategy(self, service_name: str = "unknown") -> AsyncRetrying:
        """
        Build a tenacity retry strategy from RetryConfig.
        
        Args:
            service_name: Name of the service (for logging)
        
        Returns:
            Configured AsyncRetrying instance
        """
        # Build wait strategy: exponential backoff
        # tenacity's wait_exponential uses multiplier as base delay
        # Formula: multiplier * (2 ^ (attempt - 1))
        wait_strategy = wait_exponential(
            multiplier=self.config.initial_delay,
            min=self.config.initial_delay,
            max=self.config.max_delay,
        )
        
        # Add jitter if enabled (random between 0 and 50% of initial delay)
        if self.config.jitter:
            wait_strategy = wait_strategy + wait_random(0, self.config.initial_delay * 0.5)
        
        # Build retry condition based on error categories
        retry_condition = retry_if_exception(self._should_retry_exception)
        
        # Build stop condition
        stop_condition = stop_after_attempt(self.config.max_attempts)
        
        # Build logging callbacks
        before_sleep = before_sleep_log(logger, logging.DEBUG)
        after_retry = after_log(logger, logging.WARNING)
        
        return AsyncRetrying(
            stop=stop_condition,
            wait=wait_strategy,
            retry=retry_condition,
            before_sleep=before_sleep,
            after=after_retry,
            reraise=True,  # Re-raise the last exception if all retries fail
        )


class FailureTolerantExecutor:
    """
    Executes operations with failure tolerance, retries, and escalation.
    """
    
    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        error_classifier: Optional[ErrorClassifier] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
    ):
        self.retry_config = retry_config or RetryConfig()
        self.error_classifier = error_classifier or ErrorClassifier()
        self.retry_strategy = RetryStrategy(self.retry_config, self.error_classifier)
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()
        self.circuit_breakers: dict[str, pybreaker.CircuitBreaker] = {}  # Service name -> pybreaker instance
    
    async def execute(
        self,
        operation: Callable[[], Any],
        service_name: str = "unknown",
        operation_name: str = "operation",
        timeout: Optional[float] = None,
        fallback: Optional[Callable[[], Any]] = None,
        escalation_handler: Optional[Callable[[FailureContext], EscalationLevel]] = None,
    ) -> ExecutionResult:
        """
        Execute an operation with failure tolerance.
        
        Args:
            operation: Async callable to execute
            service_name: Name of the service (for logging and circuit breaker)
            operation_name: Name of the operation (for logging)
            timeout: Optional timeout in seconds
            fallback: Optional fallback operation to try if main operation fails
            escalation_handler: Optional handler to determine escalation level
        
        Returns:
            ExecutionResult with success status and details
        """
        start_time = time.time()
        last_error = None
        last_category = None
        
        # Get or create circuit breaker for this service
        breaker = self._get_circuit_breaker(service_name)
        
        # Check if circuit is open (pybreaker will raise CircuitBreakerError if open)
        # We check state to avoid unnecessary execution
        if breaker.current_state == pybreaker.CircuitBreaker.OPEN:
            logger.warning(f"Circuit breaker is OPEN for {service_name}, skipping execution")
            return ExecutionResult(
                success=False,
                error=pybreaker.CircuitBreakerError(f"Circuit breaker is open for {service_name}"),
                category=ErrorCategory.SERVICE_UNAVAILABLE,
                attempts=0,
                elapsed_time=0.0,
            )
        
        # Build tenacity retry strategy
        retrying = self.retry_strategy.build_retry_strategy(service_name)
        
        attempt_count = 0
        last_error = None
        last_category = None
        
        # Wrap operation with timeout if specified and circuit breaker
        async def execute_with_timeout():
            nonlocal attempt_count
            attempt_count += 1
            
            # Record attempt metrics
            if METRICS_AVAILABLE:
                MetricsCollector.record_operation_attempt(
                    service_name, operation_name, attempt_count
                )
            
            # Wrap async operation for circuit breaker
            # pybreaker doesn't have native async support, so we manually track success/failure
            try:
                if timeout:
                    result = await asyncio.wait_for(operation(), timeout=timeout)
                else:
                    result = await operation()
                
                # Mark success in circuit breaker
                breaker.call_succeeded()
                
                # Record success metrics
                if METRICS_AVAILABLE:
                    MetricsCollector.record_circuit_breaker_success(service_name)
                
                return result
            except Exception as e:
                # Mark failure in circuit breaker
                breaker.call_failed()
                
                # Record failure metrics
                if METRICS_AVAILABLE:
                    MetricsCollector.record_circuit_breaker_failure(service_name)
                
                raise
        
        try:
            # Execute with tenacity retry logic
            result = await retrying(execute_with_timeout)
            
            # Success - record and return
            elapsed_time = time.time() - start_time
            
            # Log success
            if STRUCTLOG_AVAILABLE:
                logger.info(
                    "operation_succeeded",
                    service=service_name,
                    operation=operation_name,
                    attempts=attempt_count,
                    duration=elapsed_time
                )
            else:
                logger.info(
                    f"Operation '{operation_name}' succeeded on attempt {attempt_count} "
                    f"(service: {service_name}, elapsed: {elapsed_time:.2f}s)"
                )
            
            # Record metrics
            if METRICS_AVAILABLE:
                MetricsCollector.record_operation_success(service_name, operation_name)
                MetricsCollector.record_operation_duration(
                    service_name, operation_name, elapsed_time, success=True
                )
            
            return ExecutionResult(
                success=True,
                value=result,
                attempts=attempt_count,
                elapsed_time=elapsed_time,
            )
        
        except pybreaker.CircuitBreakerError as e:
            # Circuit breaker is open
            last_error = e
            last_category = ErrorCategory.SERVICE_UNAVAILABLE
            
            if STRUCTLOG_AVAILABLE:
                logger.warning(
                    "operation_blocked_by_circuit_breaker",
                    service=service_name,
                    operation=operation_name,
                    attempts=attempt_count
                )
            else:
                logger.warning(
                    f"Operation '{operation_name}' blocked by circuit breaker "
                    f"(service: {service_name})"
                )
            
            if METRICS_AVAILABLE:
                MetricsCollector.record_operation_failure(
                    service_name, operation_name, last_category.value
                )
        
        except asyncio.TimeoutError as e:
            last_error = e
            last_category = ErrorCategory.TIMEOUT
            
            if STRUCTLOG_AVAILABLE:
                logger.warning(
                    "operation_timed_out",
                    service=service_name,
                    operation=operation_name,
                    attempts=attempt_count
                )
            else:
                logger.warning(
                    f"Operation '{operation_name}' timed out after {attempt_count} attempts "
                    f"(service: {service_name})"
                )
            
            if METRICS_AVAILABLE:
                MetricsCollector.record_operation_failure(
                    service_name, operation_name, last_category.value
                )
        
        except Exception as e:
            last_error = e
            last_category = self.error_classifier.classify(e, service_name)
            
            if STRUCTLOG_AVAILABLE:
                logger.warning(
                    "operation_failed",
                    service=service_name,
                    operation=operation_name,
                    attempts=attempt_count,
                    error_category=last_category.value,
                    error=str(e)[:100]
                )
            else:
                logger.warning(
                    f"Operation '{operation_name}' failed after {attempt_count} attempts "
                    f"(service: {service_name}, category: {last_category.value}, error: {str(e)[:100]})"
                )
            
            if METRICS_AVAILABLE:
                MetricsCollector.record_operation_failure(
                    service_name, operation_name, last_category.value
                )
                MetricsCollector.record_operation_duration(
                    service_name, operation_name, time.time() - start_time, success=False
                )
        
        # All retries exhausted - try fallback or escalate
        elapsed_time = time.time() - start_time
        
        failure_context = FailureContext(
            error=last_error,
            category=last_category,
            attempt_number=self.retry_config.max_attempts,
            total_attempts=self.retry_config.max_attempts,
            elapsed_time=elapsed_time,
            service_name=service_name,
            operation_name=operation_name,
        )
        
        # Try fallback if available
        if fallback:
            if STRUCTLOG_AVAILABLE:
                logger.info(
                    "attempting_fallback",
                    service=service_name,
                    operation=operation_name
                )
            else:
                logger.info(f"Attempting fallback for '{operation_name}' (service: {service_name})")
            
            try:
                fallback_result = await fallback()
                
                if STRUCTLOG_AVAILABLE:
                    logger.info(
                        "fallback_succeeded",
                        service=service_name,
                        operation=operation_name
                    )
                else:
                    logger.info(f"Fallback succeeded for '{operation_name}' (service: {service_name})")
                
                if METRICS_AVAILABLE:
                    MetricsCollector.record_fallback_usage(
                        service_name, operation_name, "fallback_service"
                    )
                
                return ExecutionResult(
                    success=True,
                    value=fallback_result,
                    attempts=self.retry_config.max_attempts + 1,
                    elapsed_time=time.time() - start_time,
                    escalated=True,
                    escalation_level=EscalationLevel.FALLBACK_SERVICE,
                )
            except Exception as fallback_error:
                if STRUCTLOG_AVAILABLE:
                    logger.error(
                        "fallback_failed",
                        service=service_name,
                        operation=operation_name,
                        error=str(fallback_error)
                    )
                else:
                    logger.error(f"Fallback also failed for '{operation_name}': {fallback_error}")
        
        # Determine escalation level
        escalation_level = EscalationLevel.ABORT
        if escalation_handler:
            escalation_level = escalation_handler(failure_context)
        elif last_category in [ErrorCategory.AUTHENTICATION, ErrorCategory.INVALID_INPUT]:
            escalation_level = EscalationLevel.ABORT
        elif last_category == ErrorCategory.QUOTA_EXCEEDED:
            escalation_level = EscalationLevel.HUMAN_TRANSFER
        
        if STRUCTLOG_AVAILABLE:
            logger.error(
                "operation_failed_after_retries",
                service=service_name,
                operation=operation_name,
                attempts=self.retry_config.max_attempts,
                error_category=last_category.value if last_category else "unknown",
                escalation_level=escalation_level.value
            )
        else:
            logger.error(
                f"Operation '{operation_name}' failed after {self.retry_config.max_attempts} attempts "
                f"(service: {service_name}, category: {last_category.value}, "
                f"escalation: {escalation_level.value})"
            )
        
        if METRICS_AVAILABLE:
            MetricsCollector.record_escalation(
                service_name, operation_name, escalation_level.value
            )
        
        return ExecutionResult(
            success=False,
            error=last_error,
            category=last_category,
            attempts=self.retry_config.max_attempts,
            elapsed_time=elapsed_time,
            escalated=True,
            escalation_level=escalation_level,
        )
    
    def _get_circuit_breaker(self, service_name: str) -> pybreaker.CircuitBreaker:
        """Get or create a circuit breaker for a service."""
        if service_name not in self.circuit_breakers:
            # Create a new circuit breaker with configuration
            breaker = pybreaker.CircuitBreaker(
                fail_max=self.circuit_breaker_config.failure_threshold,
                timeout_duration=self.circuit_breaker_config.timeout,
                expected_exception=self.circuit_breaker_config.expected_exception,
                listeners=self.circuit_breaker_config.listeners,
            )
            
            # Add logging listener if not already present
            if not any(isinstance(l, CircuitBreakerLoggingListener) for l in breaker.listeners):
                breaker.listeners.append(CircuitBreakerLoggingListener(service_name))
            
            self.circuit_breakers[service_name] = breaker
            
            if STRUCTLOG_AVAILABLE:
                logger.debug("circuit_breaker_created", service=service_name)
            else:
                logger.debug(f"Created circuit breaker for {service_name}")
            
            # Record initial state
            if METRICS_AVAILABLE:
                MetricsCollector.record_circuit_breaker_state(service_name, 'closed')
        
        return self.circuit_breakers[service_name]


class CircuitBreakerLoggingListener(pybreaker.CircuitBreakerListener):
    """Logging listener for circuit breaker state changes."""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
    
    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: str, new_state: str):
        """Called when circuit breaker state changes."""
        if STRUCTLOG_AVAILABLE:
            logger.warning(
                "circuit_breaker_state_change",
                service=self.service_name,
                old_state=old_state,
                new_state=new_state
            )
        else:
            logger.warning(
                f"Circuit breaker for {self.service_name} changed state: {old_state} -> {new_state}"
            )
        
        if METRICS_AVAILABLE:
            MetricsCollector.record_circuit_breaker_state_change(
                self.service_name, old_state, new_state
            )
            MetricsCollector.record_circuit_breaker_state(self.service_name, new_state)
    
    def failure(self, cb: pybreaker.CircuitBreaker, exc: Exception):
        """Called when a failure is recorded."""
        if STRUCTLOG_AVAILABLE:
            logger.debug(
                "circuit_breaker_failure",
                service=self.service_name,
                error=str(exc)
            )
        else:
            logger.debug(f"Circuit breaker for {self.service_name} recorded failure: {exc}")
    
    def success(self, cb: pybreaker.CircuitBreaker):
        """Called when a success is recorded."""
        if STRUCTLOG_AVAILABLE:
            logger.debug("circuit_breaker_success", service=self.service_name)
        else:
            logger.debug(f"Circuit breaker for {self.service_name} recorded success")
    
    def opened(self, cb: pybreaker.CircuitBreaker, exc: Exception):
        """Called when circuit breaker opens."""
        if STRUCTLOG_AVAILABLE:
            logger.warning(
                "circuit_breaker_opened",
                service=self.service_name,
                failures=cb.fail_counter
            )
        else:
            logger.warning(
                f"Circuit breaker for {self.service_name} OPENED after {cb.fail_counter} failures"
            )
    
    def closed(self, cb: pybreaker.CircuitBreaker):
        """Called when circuit breaker closes."""
        if STRUCTLOG_AVAILABLE:
            logger.info("circuit_breaker_closed", service=self.service_name)
        else:
            logger.info(f"Circuit breaker for {self.service_name} CLOSED (recovered)")
    
    def half_opened(self, cb: pybreaker.CircuitBreaker):
        """Called when circuit breaker enters half-open state."""
        if STRUCTLOG_AVAILABLE:
            logger.info("circuit_breaker_half_opened", service=self.service_name)
        else:
            logger.info(f"Circuit breaker for {self.service_name} entered HALF-OPEN state (testing)")


# Convenience decorator for failure-tolerant execution
def failure_tolerant(
    service_name: str = "unknown",
    operation_name: str = "operation",
    max_attempts: int = 3,
    timeout: Optional[float] = None,
    fallback: Optional[Callable[[], Any]] = None,
):
    """
    Decorator for failure-tolerant execution.
    
    Usage:
        @failure_tolerant(service_name="openai", operation_name="llm_call", max_attempts=3)
        async def my_operation():
            # Your code here
            return result
    """
    def decorator(func: Callable[[], Any]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            executor = FailureTolerantExecutor(
                retry_config=RetryConfig(max_attempts=max_attempts)
            )
            
            async def operation():
                return await func(*args, **kwargs)
            
            result = await executor.execute(
                operation=operation,
                service_name=service_name,
                operation_name=operation_name,
                timeout=timeout,
                fallback=fallback,
            )
            
            if result.success:
                return result.value
            else:
                raise result.error
        
        return wrapper
    return decorator


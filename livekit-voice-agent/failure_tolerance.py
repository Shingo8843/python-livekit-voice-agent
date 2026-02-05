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

logger = logging.getLogger(__name__)

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
    """Implements retry strategies with exponential backoff."""
    
    def __init__(self, config: RetryConfig):
        self.config = config
    
    async def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry attempt.
        
        Args:
            attempt: Current attempt number (0-indexed)
        
        Returns:
            Delay in seconds
        """
        if attempt == 0:
            return 0.0
        
        # Exponential backoff: initial_delay * (base ^ (attempt - 1))
        delay = self.config.initial_delay * (self.config.exponential_base ** (attempt - 1))
        
        # Cap at max_delay
        delay = min(delay, self.config.max_delay)
        
        # Add jitter if enabled (random factor between 0.5 and 1.5)
        if self.config.jitter:
            import random
            jitter_factor = 0.5 + random.random()  # 0.5 to 1.5
            delay *= jitter_factor
        
        return delay
    
    def should_retry(self, category: ErrorCategory, attempt: int) -> bool:
        """
        Determine if an error should be retried.
        
        Args:
            category: Error category
            attempt: Current attempt number
        
        Returns:
            True if should retry, False otherwise
        """
        if attempt >= self.config.max_attempts:
            return False
        
        return category in self.config.retryable_categories


class FailureTolerantExecutor:
    """
    Executes operations with failure tolerance, retries, and escalation.
    """
    
    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        error_classifier: Optional[ErrorClassifier] = None,
    ):
        self.retry_config = retry_config or RetryConfig()
        self.retry_strategy = RetryStrategy(self.retry_config)
        self.error_classifier = error_classifier or ErrorClassifier()
        self.circuit_breakers: dict[str, dict] = {}  # Service name -> circuit breaker state
    
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
        
        # Check circuit breaker
        if self._is_circuit_open(service_name):
            logger.warning(f"Circuit breaker is OPEN for {service_name}, skipping execution")
            return ExecutionResult(
                success=False,
                error=Exception(f"Circuit breaker is open for {service_name}"),
                category=ErrorCategory.SERVICE_UNAVAILABLE,
                attempts=0,
                elapsed_time=0.0,
            )
        
        for attempt in range(self.retry_config.max_attempts):
            try:
                # Execute with optional timeout
                if timeout:
                    result = await asyncio.wait_for(operation(), timeout=timeout)
                else:
                    result = await operation()
                
                # Success - record and return
                elapsed_time = time.time() - start_time
                self._record_success(service_name)
                
                logger.info(
                    f"Operation '{operation_name}' succeeded on attempt {attempt + 1} "
                    f"(service: {service_name}, elapsed: {elapsed_time:.2f}s)"
                )
                
                return ExecutionResult(
                    success=True,
                    value=result,
                    attempts=attempt + 1,
                    elapsed_time=elapsed_time,
                )
            
            except asyncio.TimeoutError as e:
                last_error = e
                last_category = ErrorCategory.TIMEOUT
                logger.warning(
                    f"Operation '{operation_name}' timed out on attempt {attempt + 1} "
                    f"(service: {service_name})"
                )
            
            except Exception as e:
                last_error = e
                last_category = self.error_classifier.classify(e, service_name)
                logger.warning(
                    f"Operation '{operation_name}' failed on attempt {attempt + 1} "
                    f"(service: {service_name}, category: {last_category.value}, error: {str(e)[:100]})"
                )
            
            # Determine if we should retry
            if not self.retry_strategy.should_retry(last_category, attempt + 1):
                break
            
            # Calculate delay and wait
            delay = await self.retry_strategy.calculate_delay(attempt + 1)
            if delay > 0:
                logger.debug(f"Waiting {delay:.2f}s before retry attempt {attempt + 2}")
                await asyncio.sleep(delay)
        
        # All retries exhausted - try fallback or escalate
        elapsed_time = time.time() - start_time
        self._record_failure(service_name)
        
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
            logger.info(f"Attempting fallback for '{operation_name}' (service: {service_name})")
            try:
                fallback_result = await fallback()
                logger.info(f"Fallback succeeded for '{operation_name}' (service: {service_name})")
                return ExecutionResult(
                    success=True,
                    value=fallback_result,
                    attempts=self.retry_config.max_attempts + 1,
                    elapsed_time=time.time() - start_time,
                    escalated=True,
                    escalation_level=EscalationLevel.FALLBACK_SERVICE,
                )
            except Exception as fallback_error:
                logger.error(f"Fallback also failed for '{operation_name}': {fallback_error}")
        
        # Determine escalation level
        escalation_level = EscalationLevel.ABORT
        if escalation_handler:
            escalation_level = escalation_handler(failure_context)
        elif last_category in [ErrorCategory.AUTHENTICATION, ErrorCategory.INVALID_INPUT]:
            escalation_level = EscalationLevel.ABORT
        elif last_category == ErrorCategory.QUOTA_EXCEEDED:
            escalation_level = EscalationLevel.HUMAN_TRANSFER
        
        logger.error(
            f"Operation '{operation_name}' failed after {self.retry_config.max_attempts} attempts "
            f"(service: {service_name}, category: {last_category.value}, "
            f"escalation: {escalation_level.value})"
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
    
    def _is_circuit_open(self, service_name: str) -> bool:
        """Check if circuit breaker is open for a service."""
        if service_name not in self.circuit_breakers:
            return False
        
        breaker = self.circuit_breakers[service_name]
        if breaker['state'] == 'open':
            # Check if we should try again (half-open state)
            if time.time() - breaker['last_failure'] > 60:  # 60 second cooldown
                breaker['state'] = 'half-open'
                return False
            return True
        
        return False
    
    def _record_success(self, service_name: str):
        """Record a successful operation (for circuit breaker)."""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = {
                'state': 'closed',
                'success_count': 0,
                'failure_count': 0,
                'last_failure': 0,
            }
        
        breaker = self.circuit_breakers[service_name]
        breaker['success_count'] += 1
        
        # Reset circuit breaker on success
        if breaker['state'] == 'half-open':
            breaker['state'] = 'closed'
            breaker['failure_count'] = 0
    
    def _record_failure(self, service_name: str):
        """Record a failed operation (for circuit breaker)."""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = {
                'state': 'closed',
                'success_count': 0,
                'failure_count': 0,
                'last_failure': 0,
            }
        
        breaker = self.circuit_breakers[service_name]
        breaker['failure_count'] += 1
        breaker['last_failure'] = time.time()
        
        # Open circuit breaker after 5 consecutive failures
        if breaker['failure_count'] >= 5:
            breaker['state'] = 'open'
            logger.warning(f"Circuit breaker OPENED for {service_name} after 5 failures")


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


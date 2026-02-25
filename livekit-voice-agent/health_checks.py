"""
Health check system for proactive service monitoring.

Provides health checks for services, health scoring, and health-based
circuit breaker decisions.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Any
from collections import deque

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status of a service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    healthy: bool
    status: HealthStatus
    response_time: float
    error: Optional[Exception] = None
    message: Optional[str] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ServiceHealthChecker:
    """Proactively checks service health."""
    
    def __init__(self, check_interval: float = 60.0):
        self.check_interval = check_interval
        self.health_results: dict[str, deque] = {}  # service -> recent results
        self.health_scores: dict[str, float] = {}  # service -> health score (0.0-1.0)
        self.check_tasks: dict[str, asyncio.Task] = {}
        self.running = False
        self.max_results_history = 100
    
    async def check_health(
        self,
        service_name: str,
        check_function: Optional[Callable[[], Any]] = None
    ) -> HealthCheckResult:
        """
        Perform health check for a service.
        
        Args:
            service_name: Name of the service to check
            check_function: Optional custom health check function
        
        Returns:
            HealthCheckResult with health status
        """
        start_time = time.time()
        
        try:
            if check_function:
                # Use custom health check function
                await check_function()
                response_time = time.time() - start_time
                
                return HealthCheckResult(
                    healthy=True,
                    status=HealthStatus.HEALTHY,
                    response_time=response_time,
                    message="Health check passed"
                )
            else:
                # Default: lightweight ping check
                # This is a placeholder - implement actual health check logic
                response_time = time.time() - start_time
                
                # For now, assume healthy if check completes quickly
                healthy = response_time < 1.0
                
                return HealthCheckResult(
                    healthy=healthy,
                    status=HealthStatus.HEALTHY if healthy else HealthStatus.DEGRADED,
                    response_time=response_time,
                    message="Health check completed"
                )
        
        except Exception as e:
            response_time = time.time() - start_time
            logger.warning(f"Health check failed for {service_name}: {e}")
            
            return HealthCheckResult(
                healthy=False,
                status=HealthStatus.UNHEALTHY,
                response_time=response_time,
                error=e,
                message=f"Health check failed: {str(e)}"
            )
    
    def record_health_result(self, service_name: str, result: HealthCheckResult):
        """Record a health check result."""
        if service_name not in self.health_results:
            self.health_results[service_name] = deque(maxlen=self.max_results_history)
        
        self.health_results[service_name].append(result)
        self._update_health_score(service_name)
    
    def _update_health_score(self, service_name: str):
        """Update health score based on recent results."""
        if service_name not in self.health_results:
            self.health_scores[service_name] = 0.0
            return
        
        results = list(self.health_results[service_name])
        if not results:
            self.health_scores[service_name] = 0.0
            return
        
        # Calculate health score (0.0 to 1.0)
        # Factors:
        # - Recent success rate (40%)
        # - Average response time (30%)
        # - Consistency (30%)
        
        recent_results = results[-20:] if len(results) >= 20 else results
        
        # Success rate
        success_count = sum(1 for r in recent_results if r.healthy)
        success_rate = success_count / len(recent_results) if recent_results else 0.0
        
        # Response time score (faster = better, normalized to 0-1)
        avg_response_time = sum(r.response_time for r in recent_results) / len(recent_results)
        response_time_score = max(0.0, 1.0 - (avg_response_time / 5.0))  # 5s = 0 score
        
        # Consistency (lower variance = better)
        if len(recent_results) > 1:
            response_times = [r.response_time for r in recent_results]
            mean_rt = sum(response_times) / len(response_times)
            variance = sum((rt - mean_rt) ** 2 for rt in response_times) / len(response_times)
            consistency_score = max(0.0, 1.0 - (variance / 10.0))  # Normalize variance
        else:
            consistency_score = 1.0
        
        # Weighted combination
        health_score = (
            success_rate * 0.4 +
            response_time_score * 0.3 +
            consistency_score * 0.3
        )
        
        self.health_scores[service_name] = max(0.0, min(1.0, health_score))
    
    def get_health_score(self, service_name: str) -> float:
        """Get current health score for a service."""
        return self.health_scores.get(service_name, 0.5)  # Default to 0.5 (unknown)
    
    def get_health_status(self, service_name: str) -> HealthStatus:
        """Get current health status for a service."""
        score = self.get_health_score(service_name)
        
        if score >= 0.8:
            return HealthStatus.HEALTHY
        elif score >= 0.5:
            return HealthStatus.DEGRADED
        elif score > 0.0:
            return HealthStatus.UNHEALTHY
        else:
            return HealthStatus.UNKNOWN
    
    async def start_periodic_checks(
        self,
        services: dict[str, Optional[Callable[[], Any]]]
    ):
        """Start periodic health checks for services."""
        self.running = True
        
        async def check_loop(service_name: str, check_func: Optional[Callable]):
            while self.running:
                try:
                    result = await self.check_health(service_name, check_func)
                    self.record_health_result(service_name, result)
                    
                    logger.debug(
                        f"Health check for {service_name}: "
                        f"{result.status.value} (score: {self.get_health_score(service_name):.2f})"
                    )
                except Exception as e:
                    logger.error(f"Error in health check loop for {service_name}: {e}")
                
                await asyncio.sleep(self.check_interval)
        
        # Start check loops for each service
        for service_name, check_func in services.items():
            task = asyncio.create_task(check_loop(service_name, check_func))
            self.check_tasks[service_name] = task
        
        logger.info(f"Started periodic health checks for {len(services)} services")
    
    async def stop_periodic_checks(self):
        """Stop periodic health checks."""
        self.running = False
        
        # Cancel all check tasks
        for task in self.check_tasks.values():
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self.check_tasks.values(), return_exceptions=True)
        
        self.check_tasks.clear()
        logger.info("Stopped periodic health checks")
    
    def should_bypass_circuit_breaker(
        self,
        service_name: str,
        circuit_state: str
    ) -> bool:
        """
        Determine if circuit breaker should be bypassed based on health.
        
        Args:
            service_name: Name of the service
            circuit_state: Current circuit breaker state
        
        Returns:
            True if circuit breaker should be bypassed (service appears healthy)
        """
        if circuit_state != 'open':
            return False
        
        # If circuit is open but health check shows service is healthy,
        # allow a test request (half-open behavior)
        health_status = self.get_health_status(service_name)
        health_score = self.get_health_score(service_name)
        
        # Bypass if health is good and recent checks show recovery
        if health_status == HealthStatus.HEALTHY and health_score >= 0.8:
            # Check if we have recent successful health checks
            if service_name in self.health_results:
                recent_results = list(self.health_results[service_name])[-5:]
                if recent_results and all(r.healthy for r in recent_results):
                    logger.info(
                        f"Bypassing circuit breaker for {service_name} "
                        f"due to good health (score: {health_score:.2f})"
                    )
                    return True
        
        return False


# Global health checker instance
_global_health_checker: Optional[ServiceHealthChecker] = None


def get_health_checker() -> ServiceHealthChecker:
    """Get or create global health checker instance."""
    global _global_health_checker
    if _global_health_checker is None:
        _global_health_checker = ServiceHealthChecker()
    return _global_health_checker


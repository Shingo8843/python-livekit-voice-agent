"""
Escalation management for handling failures and uncertainty.

This module provides escalation strategies for different failure scenarios,
including graceful degradation, human transfer, and partial failure handling.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Callable

from livekit.agents import AgentSession

from .failure_tolerance import (
    ErrorCategory,
    EscalationLevel,
    FailureContext,
    ExecutionResult,
)

logger = logging.getLogger(__name__)


class DegradationMode(Enum):
    """Modes of graceful degradation."""
    FULL_FUNCTIONALITY = "full"  # All services working
    REDUCED_STT = "reduced_stt"  # STT degraded (slower, less accurate)
    REDUCED_TTS = "reduced_tts"  # TTS degraded (fallback voice)
    REDUCED_LLM = "reduced_llm"  # LLM degraded (simpler model)
    TEXT_ONLY = "text_only"  # Only text-based communication
    MINIMAL = "minimal"  # Minimal functionality, prepare for transfer


@dataclass
class EscalationPolicy:
    """Policy for handling escalations."""
    max_retries_before_escalation: int = 3
    enable_graceful_degradation: bool = True
    enable_human_transfer: bool = True
    human_transfer_threshold: int = 5  # Number of failures before transfer
    degradation_sequence: list[DegradationMode] = None
    
    def __post_init__(self):
        if self.degradation_sequence is None:
            self.degradation_sequence = [
                DegradationMode.FULL_FUNCTIONALITY,
                DegradationMode.REDUCED_TTS,
                DegradationMode.REDUCED_LLM,
                DegradationMode.REDUCED_STT,
                DegradationMode.TEXT_ONLY,
                DegradationMode.MINIMAL,
            ]


class EscalationManager:
    """Manages escalation and graceful degradation."""
    
    def __init__(self, session: AgentSession, policy: Optional[EscalationPolicy] = None):
        self.session = session
        self.policy = policy or EscalationPolicy()
        self.current_mode = DegradationMode.FULL_FUNCTIONALITY
        self.failure_count = 0
        self.service_failures: dict[str, int] = {}  # service_name -> failure count
    
    def record_failure(self, service_name: str, context: FailureContext):
        """Record a failure and update escalation state."""
        self.failure_count += 1
        self.service_failures[service_name] = self.service_failures.get(service_name, 0) + 1
        
        logger.warning(
            f"Recorded failure for {service_name} "
            f"(total failures: {self.failure_count}, service failures: {self.service_failures[service_name]})"
        )
        
        # Determine if we should escalate
        if self.should_escalate_to_human():
            return EscalationLevel.HUMAN_TRANSFER
        
        # Determine if we should degrade
        if self.policy.enable_graceful_degradation:
            new_mode = self._determine_degradation_mode()
            if new_mode != self.current_mode:
                self._transition_to_mode(new_mode)
                return EscalationLevel.GRACEFUL_DEGRADATION
        
        return EscalationLevel.RETRY_WITH_BACKOFF
    
    def should_escalate_to_human(self) -> bool:
        """Determine if we should escalate to human agent."""
        if not self.policy.enable_human_transfer:
            return False
        
        # Escalate if total failures exceed threshold
        if self.failure_count >= self.policy.human_transfer_threshold:
            return True
        
        # Escalate if critical service has persistent failures
        critical_services = ["openai_llm", "deepgram_stt"]
        for service in critical_services:
            if self.service_failures.get(service, 0) >= 3:
                return True
        
        return False
    
    def _determine_degradation_mode(self) -> DegradationMode:
        """Determine the appropriate degradation mode based on failures."""
        # Check which services are failing
        stt_failures = self.service_failures.get("deepgram_stt", 0)
        tts_failures = self.service_failures.get("elevenlabs_tts", 0) + self.service_failures.get("cartesia_tts", 0)
        llm_failures = self.service_failures.get("openai_llm", 0)
        
        # Determine mode based on failure patterns
        if llm_failures >= 2:
            return DegradationMode.REDUCED_LLM
        elif tts_failures >= 2:
            return DegradationMode.REDUCED_TTS
        elif stt_failures >= 2:
            return DegradationMode.REDUCED_STT
        elif self.failure_count >= 4:
            return DegradationMode.TEXT_ONLY
        elif self.failure_count >= 6:
            return DegradationMode.MINIMAL
        
        return self.current_mode
    
    def _transition_to_mode(self, new_mode: DegradationMode):
        """Transition to a new degradation mode."""
        if new_mode == self.current_mode:
            return
        
        logger.info(f"Transitioning from {self.current_mode.value} to {new_mode.value}")
        self.current_mode = new_mode
        
        # Notify user if transitioning to degraded mode
        if new_mode != DegradationMode.FULL_FUNCTIONALITY:
            self._notify_degradation(new_mode)
    
    async def _notify_degradation(self, mode: DegradationMode):
        """Notify user about degradation mode."""
        messages = {
            DegradationMode.REDUCED_TTS: "I'm experiencing some technical difficulties with my voice. I'll continue to assist you.",
            DegradationMode.REDUCED_LLM: "I'm operating with reduced capabilities. I'll do my best to help you.",
            DegradationMode.REDUCED_STT: "I may have difficulty understanding you clearly. Please speak slowly and clearly.",
            DegradationMode.TEXT_ONLY: "I'm switching to text-only mode due to technical issues.",
            DegradationMode.MINIMAL: "I'm experiencing significant technical difficulties. Let me transfer you to a human agent.",
        }
        
        message = messages.get(mode)
        if message:
            try:
                await self.session.say(message, allow_interruptions=False)
            except Exception as e:
                logger.error(f"Failed to notify user about degradation: {e}")
    
    async def handle_escalation(
        self,
        result: ExecutionResult,
        service_name: str,
        context: FailureContext,
    ) -> bool:
        """
        Handle escalation based on result and context.
        
        Args:
            result: Execution result
            service_name: Name of the service that failed
            context: Failure context
        
        Returns:
            True if escalation was handled, False otherwise
        """
        if result.success:
            return True
        
        escalation_level = self.record_failure(service_name, context)
        
        if escalation_level == EscalationLevel.HUMAN_TRANSFER:
            await self._transfer_to_human(context)
            return True
        elif escalation_level == EscalationLevel.GRACEFUL_DEGRADATION:
            # Degradation already handled in record_failure
            return True
        
        return False
    
    async def _transfer_to_human(self, context: FailureContext):
        """Transfer to human agent."""
        logger.info("Initiating transfer to human agent")
        
        try:
            # Try to use transfer_to_human tool if available
            # This would be called through the agent's tool system
            transfer_message = (
                "I'm experiencing technical difficulties and would like to transfer you "
                "to a human agent who can better assist you. Please hold for just a moment."
            )
            await self.session.say(transfer_message, allow_interruptions=False)
            
            # In a real implementation, this would trigger actual transfer logic
            # For now, we log it
            logger.info("Transfer to human agent initiated")
            
        except Exception as e:
            logger.error(f"Failed to transfer to human agent: {e}")
            # Last resort: apologize and end call gracefully
            try:
                await self.session.say(
                    "I apologize, but I'm unable to continue this call due to technical issues. "
                    "Please call back or contact support. Goodbye.",
                    allow_interruptions=False,
                )
            except:
                pass  # If even this fails, just log and continue
    
    def get_current_capabilities(self) -> dict[str, bool]:
        """Get current capabilities based on degradation mode."""
        capabilities = {
            "stt": True,
            "tts": True,
            "llm": True,
            "full_voice": True,
        }
        
        if self.current_mode == DegradationMode.MINIMAL:
            capabilities = {k: False for k in capabilities}
        elif self.current_mode == DegradationMode.TEXT_ONLY:
            capabilities["full_voice"] = False
        elif self.current_mode == DegradationMode.REDUCED_STT:
            capabilities["stt"] = False
        elif self.current_mode == DegradationMode.REDUCED_TTS:
            capabilities["tts"] = False
        elif self.current_mode == DegradationMode.REDUCED_LLM:
            capabilities["llm"] = False
        
        return capabilities


class UncertaintyHandler:
    """Handles uncertainty in execution (partial failures, timeouts, ambiguous results)."""
    
    def __init__(self, session: AgentSession):
        self.session = session
        self.partial_results: list[Any] = []
        self.timeout_count = 0
    
    async def handle_partial_failure(
        self,
        partial_result: Any,
        error: Exception,
        operation_name: str,
    ) -> ExecutionResult:
        """
        Handle a partial failure where some result was obtained but operation didn't complete.
        
        Args:
            partial_result: Partial result obtained
            error: Error that occurred
            operation_name: Name of the operation
        
        Returns:
            ExecutionResult indicating whether partial result is usable
        """
        logger.warning(f"Handling partial failure for {operation_name}: {error}")
        
        # Store partial result for potential use
        self.partial_results.append({
            "operation": operation_name,
            "result": partial_result,
            "error": str(error),
        })
        
        # Determine if partial result is usable
        # This is operation-specific logic
        is_usable = self._is_partial_result_usable(partial_result, operation_name)
        
        if is_usable:
            logger.info(f"Partial result for {operation_name} is usable")
            return ExecutionResult(
                success=True,
                value=partial_result,
                escalated=True,
                escalation_level=EscalationLevel.GRACEFUL_DEGRADATION,
            )
        else:
            logger.warning(f"Partial result for {operation_name} is not usable")
            return ExecutionResult(
                success=False,
                error=error,
                category=ErrorCategory.TRANSIENT,
            )
    
    def _is_partial_result_usable(self, result: Any, operation_name: str) -> bool:
        """Determine if a partial result is usable."""
        # For transcription: if we got any text, it's usable
        if operation_name == "transcribe":
            return bool(result and len(str(result).strip()) > 0)
        
        # For TTS: if we got audio data, it's usable
        if operation_name == "synthesize":
            return result is not None
        
        # For LLM: if we got any response, it's usable
        if operation_name == "generate":
            return bool(result and len(str(result).strip()) > 0)
        
        return False
    
    async def handle_timeout(
        self,
        operation_name: str,
        timeout_duration: float,
    ) -> ExecutionResult:
        """
        Handle a timeout scenario.
        
        Args:
            operation_name: Name of the operation that timed out
            timeout_duration: Duration of the timeout
        
        Returns:
            ExecutionResult indicating timeout handling
        """
        self.timeout_count += 1
        logger.warning(
            f"Timeout for {operation_name} after {timeout_duration}s "
            f"(total timeouts: {self.timeout_count})"
        )
        
        # If multiple timeouts, suggest alternative approach
        if self.timeout_count >= 3:
            try:
                await self.session.say(
                    "I'm experiencing delays. Let me try a different approach.",
                    allow_interruptions=True,
                )
            except Exception as e:
                logger.error(f"Failed to notify about timeout: {e}")
        
        return ExecutionResult(
            success=False,
            error=TimeoutError(f"Operation {operation_name} timed out after {timeout_duration}s"),
            category=ErrorCategory.TIMEOUT,
        )
    
    def reset(self):
        """Reset uncertainty handler state."""
        self.partial_results.clear()
        self.timeout_count = 0


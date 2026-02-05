"""
Service-specific handlers with fallback mechanisms for STT, TTS, and LLM.

This module provides resilient wrappers around external services with:
- Automatic fallback to alternative services
- Service-specific retry configurations
- Graceful degradation when services are unavailable
"""

import logging
import os
from typing import Optional, Any

from livekit.plugins import deepgram, openai, cartesia, elevenlabs
from livekit.agents import AgentSession

from .failure_tolerance import (
    FailureTolerantExecutor,
    RetryConfig,
    ErrorCategory,
    EscalationLevel,
    FailureContext,
    ExecutionResult,
)

logger = logging.getLogger(__name__)


class STTHandler:
    """Handler for Speech-to-Text services with fallback support."""
    
    def __init__(self, language: str = "en"):
        self.language = language
        self.primary_stt: Optional[Any] = None
        self.fallback_stt: Optional[Any] = None
        self.executor = FailureTolerantExecutor(
            retry_config=RetryConfig(
                max_attempts=3,
                initial_delay=1.0,
                max_delay=10.0,
            )
        )
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize primary and fallback STT services."""
        try:
            # Primary: Deepgram
            deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
            if deepgram_api_key:
                if self.language.startswith("ja"):
                    model = "nova-3"
                else:
                    model = "flux-general-en"
                
                self.primary_stt = deepgram.STTv2(model=model)
                logger.info(f"Initialized Deepgram STT (model: {model})")
            else:
                logger.warning("DEEPGRAM_API_KEY not found, STT fallback may not work")
        except Exception as e:
            logger.error(f"Failed to initialize primary STT: {e}")
    
    async def transcribe(self, audio_data: Any) -> ExecutionResult:
        """
        Transcribe audio with automatic fallback.
        
        Args:
            audio_data: Audio data to transcribe
        
        Returns:
            ExecutionResult with transcription or error
        """
        if not self.primary_stt:
            return ExecutionResult(
                success=False,
                error=Exception("No STT service available"),
                category=ErrorCategory.SERVICE_UNAVAILABLE,
            )
        
        async def primary_operation():
            # This is a placeholder - actual STT call would go here
            # The actual implementation depends on LiveKit's STT interface
            return await self.primary_stt.transcribe(audio_data)
        
        return await self.executor.execute(
            operation=primary_operation,
            service_name="deepgram_stt",
            operation_name="transcribe",
            timeout=30.0,
        )


class TTSHandler:
    """Handler for Text-to-Speech services with fallback support."""
    
    def __init__(self, language: str = "en", speed: float = 1.0, volume: float = 1.0, emotion: str = "friendly"):
        self.language = language
        self.speed = speed
        self.volume = volume
        self.emotion = emotion
        self.primary_tts: Optional[Any] = None
        self.fallback_tts: Optional[Any] = None
        self.executor = FailureTolerantExecutor(
            retry_config=RetryConfig(
                max_attempts=2,  # Fewer retries for TTS (faster fallback)
                initial_delay=0.5,
                max_delay=5.0,
            )
        )
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize primary and fallback TTS services."""
        # Try ElevenLabs first (preferred)
        try:
            eleven_api_key = os.getenv("ELEVEN_API_KEY")
            if eleven_api_key:
                if self.language.startswith("ja"):
                    model = os.getenv("ELEVEN_MODEL_JA", "eleven_multilingual_v2")
                    voice_id = os.getenv("ELEVEN_VOICE_ID_JA", "EXAVITQu4vr4xnSDxMaL")
                else:
                    model = os.getenv("ELEVEN_MODEL_EN", "eleven_flash_v2_5")
                    voice_id = os.getenv("ELEVEN_VOICE_ID_EN", "ODq5zmih8GrVes37Dizd")
                
                self.primary_tts = elevenlabs.TTS(
                    model=model,
                    voice_id=voice_id,
                    stability=float(os.getenv("ELEVEN_STABILITY", "0.5")),
                    similarity_boost=float(os.getenv("ELEVEN_SIMILARITY_BOOST", "0.75")),
                )
                logger.info(f"Initialized ElevenLabs TTS (model: {model}, language: {self.language})")
        except Exception as e:
            logger.warning(f"Failed to initialize ElevenLabs TTS: {e}")
        
        # Fallback: Cartesia
        try:
            cartesia_api_key = os.getenv("CARTESIA_API_KEY")
            if cartesia_api_key:
                if self.language.startswith("ja"):
                    voice = "0834f3df-e650-4766-a20c-5a93a43aa6e3"  # Japanese voice
                else:
                    voice = "0834f3df-e650-4766-a20c-5a93a43aa6e3"  # English voice
                
                self.fallback_tts = cartesia.TTS(
                    model="sonic-3",
                    voice=voice,
                    language=self.language,
                    speed=self.speed,
                    volume=self.volume,
                    emotion=self.emotion,
                )
                logger.info(f"Initialized Cartesia TTS (fallback, language: {self.language})")
        except Exception as e:
            logger.warning(f"Failed to initialize Cartesia TTS fallback: {e}")
        
        # If no primary, use fallback as primary
        if not self.primary_tts and self.fallback_tts:
            self.primary_tts = self.fallback_tts
            self.fallback_tts = None
            logger.info("Using Cartesia TTS as primary (no ElevenLabs available)")
    
    async def synthesize(self, text: str) -> ExecutionResult:
        """
        Synthesize speech with automatic fallback.
        
        Args:
            text: Text to synthesize
        
        Returns:
            ExecutionResult with audio or error
        """
        if not self.primary_tts:
            return ExecutionResult(
                success=False,
                error=Exception("No TTS service available"),
                category=ErrorCategory.SERVICE_UNAVAILABLE,
            )
        
        async def primary_operation():
            return await self.primary_tts.synthesize(text)
        
        async def fallback_operation():
            if self.fallback_tts:
                logger.info("Using fallback TTS (Cartesia)")
                return await self.fallback_tts.synthesize(text)
            raise Exception("No fallback TTS available")
        
        def escalation_handler(context: FailureContext) -> EscalationLevel:
            # For TTS, prefer fallback over retry
            if self.fallback_tts and context.attempt_number >= 1:
                return EscalationLevel.FALLBACK_SERVICE
            return EscalationLevel.RETRY_WITH_BACKOFF
        
        return await self.executor.execute(
            operation=primary_operation,
            service_name="elevenlabs_tts" if self.fallback_tts else "cartesia_tts",
            operation_name="synthesize",
            timeout=30.0,
            fallback=fallback_operation if self.fallback_tts else None,
            escalation_handler=escalation_handler,
        )


class LLMHandler:
    """Handler for LLM services with retry and fallback support."""
    
    def __init__(self, model: str = "gpt-4.1"):
        self.model_name = model
        self.primary_llm: Optional[Any] = None
        self.fallback_llm: Optional[Any] = None
        self.executor = FailureTolerantExecutor(
            retry_config=RetryConfig(
                max_attempts=3,
                initial_delay=2.0,  # Longer delay for LLM (more expensive)
                max_delay=30.0,
            )
        )
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize primary and fallback LLM services."""
        try:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if openai_api_key:
                self.primary_llm = openai.LLM(model=self.model_name)
                logger.info(f"Initialized OpenAI LLM (model: {self.model_name})")
                
                # Fallback to a simpler/faster model if available
                if self.model_name.startswith("gpt-4"):
                    try:
                        self.fallback_llm = openai.LLM(model="gpt-3.5-turbo")
                        logger.info("Initialized GPT-3.5-turbo as fallback LLM")
                    except Exception as e:
                        logger.warning(f"Failed to initialize fallback LLM: {e}")
            else:
                logger.error("OPENAI_API_KEY not found")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
    
    async def generate(self, prompt: str, **kwargs) -> ExecutionResult:
        """
        Generate LLM response with automatic fallback.
        
        Args:
            prompt: Prompt text
            **kwargs: Additional arguments for LLM generation
        
        Returns:
            ExecutionResult with generated text or error
        """
        if not self.primary_llm:
            return ExecutionResult(
                success=False,
                error=Exception("No LLM service available"),
                category=ErrorCategory.SERVICE_UNAVAILABLE,
            )
        
        async def primary_operation():
            # Actual LLM call would go here
            # This depends on LiveKit's LLM interface
            return await self.primary_llm.generate(prompt, **kwargs)
        
        async def fallback_operation():
            if self.fallback_llm:
                logger.info("Using fallback LLM (GPT-3.5-turbo)")
                return await self.fallback_llm.generate(prompt, **kwargs)
            raise Exception("No fallback LLM available")
        
        def escalation_handler(context: FailureContext) -> EscalationLevel:
            # For rate limits, use longer backoff
            if context.category == ErrorCategory.RATE_LIMIT:
                return EscalationLevel.RETRY_WITH_BACKOFF
            # For quota exceeded, escalate to human
            if context.category == ErrorCategory.QUOTA_EXCEEDED:
                return EscalationLevel.HUMAN_TRANSFER
            # Try fallback after 2 attempts
            if context.attempt_number >= 2 and self.fallback_llm:
                return EscalationLevel.FALLBACK_SERVICE
            return EscalationLevel.RETRY_WITH_BACKOFF
        
        return await self.executor.execute(
            operation=primary_operation,
            service_name="openai_llm",
            operation_name="generate",
            timeout=60.0,  # Longer timeout for LLM
            fallback=fallback_operation if self.fallback_llm else None,
            escalation_handler=escalation_handler,
        )


class SessionHandler:
    """Handler for agent session operations with failure tolerance."""
    
    def __init__(self, session: AgentSession):
        self.session = session
        self.executor = FailureTolerantExecutor(
            retry_config=RetryConfig(
                max_attempts=2,  # Fewer retries for session operations
                initial_delay=1.0,
                max_delay=5.0,
            )
        )
    
    async def generate_reply(self, instructions: str, **kwargs) -> ExecutionResult:
        """
        Generate a reply with failure tolerance.
        
        Args:
            instructions: Instructions for reply generation
            **kwargs: Additional arguments
        
        Returns:
            ExecutionResult with reply or error
        """
        async def operation():
            return await self.session.generate_reply(instructions, **kwargs)
        
        def escalation_handler(context: FailureContext) -> EscalationLevel:
            # For session failures, try graceful degradation
            if context.category in [ErrorCategory.TIMEOUT, ErrorCategory.NETWORK]:
                return EscalationLevel.GRACEFUL_DEGRADATION
            return EscalationLevel.RETRY
        
        return await self.executor.execute(
            operation=operation,
            service_name="agent_session",
            operation_name="generate_reply",
            timeout=45.0,
            escalation_handler=escalation_handler,
        )
    
    async def say(self, text: str, **kwargs) -> ExecutionResult:
        """
        Say text with failure tolerance.
        
        Args:
            text: Text to say
            **kwargs: Additional arguments
        
        Returns:
            ExecutionResult with success status
        """
        async def operation():
            await self.session.say(text, **kwargs)
            return True
        
        return await self.executor.execute(
            operation=operation,
            service_name="agent_session",
            operation_name="say",
            timeout=30.0,
        )


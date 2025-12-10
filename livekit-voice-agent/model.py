"""
Conversational design model configuration for AgentSession.

This module provides language-specific configurations for conversational parameters
that control turn detection, interruptions, endpointing, and other aspects of
voice agent behavior.
"""

from dataclasses import dataclass
from typing import Literal, Optional
from livekit.plugins.turn_detector.multilingual import MultilingualModel


@dataclass
class ConversationalConfig:
    """Configuration for conversational design parameters in AgentSession."""
    
    # Turn Detection
    turn_detection: Optional[MultilingualModel] = None  # None = auto-select
    
    # Interruption Parameters
    allow_interruptions: bool = True
    discard_audio_if_uninterruptible: bool = True
    min_interruption_duration: float = 0.5  # seconds
    min_interruption_words: int = 0
    false_interruption_timeout: Optional[float] = 2.0  # seconds, None to disable
    resume_false_interruption: bool = True
    
    # Endpointing/Timing Parameters
    min_endpointing_delay: float = 0.5  # seconds
    max_endpointing_delay: float = 3.0  # seconds
    min_consecutive_speech_delay: float = 0.0  # seconds
    
    # User State Management
    user_away_timeout: Optional[float] = 15.0  # seconds, None to disable
    
    # Tool Call Parameters
    max_tool_steps: int = 3
    
    # Preemptive Generation
    preemptive_generation: bool = False
    
    # TTS Text Processing
    tts_text_transforms: Optional[list[str]] = None  # None = use defaults, [] = disable
    
    # IVR Detection
    ivr_detection: bool = False
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary for AgentSession initialization."""
        config = {}
        
        if self.turn_detection is not None:
            config["turn_detection"] = self.turn_detection
        
        config.update({
            "allow_interruptions": self.allow_interruptions,
            "discard_audio_if_uninterruptible": self.discard_audio_if_uninterruptible,
            "min_interruption_duration": self.min_interruption_duration,
            "min_interruption_words": self.min_interruption_words,
            "false_interruption_timeout": self.false_interruption_timeout,
            "resume_false_interruption": self.resume_false_interruption,
            "min_endpointing_delay": self.min_endpointing_delay,
            "max_endpointing_delay": self.max_endpointing_delay,
            "min_consecutive_speech_delay": self.min_consecutive_speech_delay,
            "user_away_timeout": self.user_away_timeout,
            "max_tool_steps": self.max_tool_steps,
            "preemptive_generation": self.preemptive_generation,
            "ivr_detection": self.ivr_detection,
        })
        
        if self.tts_text_transforms is not None:
            config["tts_text_transforms"] = self.tts_text_transforms
        
        return config


def get_conversational_config(
    language: str,
    *,
    use_turn_detector: bool = True,
    preemptive_generation: bool = False,
    user_away_timeout: Optional[float] = 15.0,
) -> ConversationalConfig:
    """
    Get conversational design configuration based on language.
    
    Args:
        language: Language code (e.g., "en-US", "ja-JP", "ja")
        use_turn_detector: Whether to use the MultilingualModel turn detector
        preemptive_generation: Whether to enable preemptive generation
        user_away_timeout: Timeout for user away state (None to disable)
    
    Returns:
        ConversationalConfig instance with language-appropriate settings
    """
    is_japanese = language.lower().startswith("ja")
    
    if is_japanese:
        # Japanese: More conservative, less overlap, longer pauses
        return ConversationalConfig(
            turn_detection=MultilingualModel() if use_turn_detector else None,
            allow_interruptions=True,
            discard_audio_if_uninterruptible=True,
            min_interruption_duration=0.8,  # Longer duration required
            min_interruption_words=2,  # Require at least 2 words
            false_interruption_timeout=2.5,  # Longer timeout
            resume_false_interruption=True,
            min_endpointing_delay=0.2,  # Slightly longer delay
            max_endpointing_delay=4.0,  # Longer max delay for Japanese
            min_consecutive_speech_delay=0.1,  # Small delay between speech segments
            user_away_timeout=user_away_timeout,
            max_tool_steps=3,
            preemptive_generation=preemptive_generation,
            tts_text_transforms=None,  # Use defaults (filter markdown, emoji)
            ivr_detection=False,
        )
    else:
        # English and other languages: More tolerant, allows slight overlap
        return ConversationalConfig(
            turn_detection=MultilingualModel() if use_turn_detector else None,
            allow_interruptions=True,
            discard_audio_if_uninterruptible=True,
            min_interruption_duration=0.3,  # Shorter duration, more responsive
            min_interruption_words=1,  # Single word can interrupt
            false_interruption_timeout=2.0,  # Standard timeout
            resume_false_interruption=True,
            min_endpointing_delay=0.05,  # Quick response
            max_endpointing_delay=3.0,  # Standard max delay
            min_consecutive_speech_delay=0.0,  # No delay needed
            user_away_timeout=user_away_timeout,
            max_tool_steps=3,
            preemptive_generation=preemptive_generation,
            tts_text_transforms=None,  # Use defaults (filter markdown, emoji)
            ivr_detection=False,
        )


def get_default_config() -> ConversationalConfig:
    """Get default conversational configuration (English-like)."""
    return get_conversational_config("en-US")


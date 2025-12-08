"""
Silence Modeling Engine for culturally-aware turn-taking and silence interpretation.

This module provides components for:
- Cultural timing rules (Japanese vs English)
- Silence state classification
- Backchannel generation
- Response timing control
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Literal, Optional

from livekit.agents import AgentSession
from livekit.agents.voice import UserInputTranscribedEvent
from livekit.agents import UserStateChangedEvent, AgentStateChangedEvent

logger = logging.getLogger(__name__)


@dataclass
class CulturalTimingRules:
    """Configuration for cultural timing rules."""
    
    language: str
    min_response_delay: float  # seconds
    max_response_delay: float  # seconds
    long_silence_threshold: float  # seconds
    backchannel_frequency: Literal["low", "medium", "high"]
    backchannel_interval: float  # minimum seconds between backchannels
    allow_overlap: bool
    min_interruption_duration: float
    silence_classification_thresholds: dict[str, float]  # thresholds for each silence type
    
    @classmethod
    def japanese(cls) -> "CulturalTimingRules":
        """Japanese cultural timing rules."""
        return cls(
            language="ja-JP",
            min_response_delay=0.2,  # 200ms
            max_response_delay=0.5,  # 500ms
            long_silence_threshold=2.0,  # 2 seconds
            backchannel_frequency="high",
            backchannel_interval=2.0,
            allow_overlap=False,
            min_interruption_duration=0.8,
            silence_classification_thresholds={
                "normal_pause": 0.3,
                "thinking": 1.0,
                "end_of_speech": 2.0,
                "disengagement": 5.0,
            },
        )
    
    @classmethod
    def english(cls) -> "CulturalTimingRules":
        """English cultural timing rules."""
        return cls(
            language="en-US",
            min_response_delay=0.05,  # 50ms
            max_response_delay=0.15,  # 150ms
            long_silence_threshold=1.0,  # 1 second
            backchannel_frequency="low",
            backchannel_interval=3.0,
            allow_overlap=True,
            min_interruption_duration=0.3,
            silence_classification_thresholds={
                "normal_pause": 0.2,
                "thinking": 0.5,
                "end_of_speech": 1.0,
                "disengagement": 3.0,
            },
        )


class SilenceStateMachine:
    """State machine for classifying silence types."""
    
    def __init__(self, timing_rules: CulturalTimingRules):
        self.rules = timing_rules
        self.state = "none"  # none, speaking, normal_pause, thinking, end_of_speech, disengagement
        self.silence_duration = 0.0
        self.last_speech_time: Optional[float] = None
        self.last_transcription_time: Optional[float] = None
        self.asr_segments: list[tuple[float, str]] = []  # (timestamp, text)
        
    def update(self, has_speech: bool, transcription_time: Optional[float] = None) -> tuple[str, bool, bool]:
        """
        Update state based on speech detection and ASR timing.
        
        Args:
            has_speech: Whether speech is currently detected
            transcription_time: Timestamp of latest transcription event
            
        Returns:
            Tuple of (state, should_respond, should_backchannel)
        """
        current_time = time.time()
        
        if has_speech:
            self.state = "speaking"
            self.silence_duration = 0.0
            self.last_speech_time = current_time
            if transcription_time:
                self.last_transcription_time = transcription_time
            return ("speaking", False, False)
        
        # Calculate silence duration
        if self.last_speech_time:
            self.silence_duration = current_time - self.last_speech_time
        elif self.last_transcription_time:
            # Fallback to transcription time if speech time not available
            self.silence_duration = current_time - self.last_transcription_time
        else:
            self.silence_duration = 0.0
        
        thresholds = self.rules.silence_classification_thresholds
        
        # Classify silence type
        if self.silence_duration < thresholds.get("normal_pause", 0.3):
            self.state = "normal_pause"
            return ("normal_pause", False, False)
        elif self.silence_duration < thresholds.get("thinking", 1.0):
            self.state = "thinking"
            # Trigger soft backchannel for high-frequency cultures
            should_backchannel = (
                self.rules.backchannel_frequency in ("high", "medium") and
                self.silence_duration > 0.5
            )
            return ("thinking", False, should_backchannel)
        elif self.silence_duration < thresholds.get("end_of_speech", 2.0):
            self.state = "end_of_speech"
            # Check if we should respond based on cultural timing
            min_delay = self.rules.min_response_delay
            max_delay = self.rules.max_response_delay
            if min_delay <= self.silence_duration <= max_delay:
                return ("end_of_speech", True, False)
            return ("end_of_speech", False, False)
        else:
            self.state = "disengagement"
            return ("disengagement", False, False)
    
    def update_transcription(self, text: str, timestamp: float):
        """Update with new transcription segment."""
        self.asr_segments.append((timestamp, text))
        self.last_transcription_time = timestamp
        # Keep only recent segments (last 5 seconds)
        cutoff = timestamp - 5.0
        self.asr_segments = [(t, txt) for t, txt in self.asr_segments if t > cutoff]
    
    def reset(self):
        """Reset state machine."""
        self.state = "none"
        self.silence_duration = 0.0
        self.last_speech_time = None
        self.last_transcription_time = None


class BackchannelManager:
    """Manages culturally-appropriate backchannel generation."""
    
    def __init__(self, language: str, session: AgentSession):
        self.language = language
        self.session = session
        self.backchannels = self._get_backchannels(language)
        self.last_backchannel_time = 0.0
        self.min_backchannel_interval = 2.0
        self._backchannel_task: Optional[asyncio.Task] = None
    
    def _get_backchannels(self, language: str) -> list[str]:
        """Get backchannel phrases for the given language."""
        if language.startswith("ja"):
            return ["はい", "ええ", "そうですね", "なるほど", "ああ"]
        else:
            return ["I see", "Okay", "Right", "Got it", "Mm-hmm"]
    
    async def trigger(self) -> bool:
        """
        Trigger a soft backchannel if appropriate.
        
        Returns:
            True if backchannel was triggered, False otherwise
        """
        current_time = time.time()
        if current_time - self.last_backchannel_time < self.min_backchannel_interval:
            return False  # Too soon for another backchannel
        
        # Check if agent is already speaking
        # We'll use a simple check - if there's a pending backchannel task, skip
        if self._backchannel_task and not self._backchannel_task.done():
            return False
        
        backchannel = random.choice(self.backchannels)
        
        try:
            # Generate backchannel without interrupting main flow
            self._backchannel_task = asyncio.create_task(
                self._say_backchannel(backchannel)
            )
            self.last_backchannel_time = current_time
            logger.info(f"Triggered backchannel: {backchannel} (language: {self.language})")
            return True
        except Exception as e:
            logger.error(f"Error triggering backchannel: {e}")
            return False
    
    async def _say_backchannel(self, text: str):
        """Say a backchannel phrase."""
        try:
            await self.session.say(
                text,
                allow_interruptions=True,  # User can interrupt backchannel
            )
        except Exception as e:
            logger.error(f"Error saying backchannel '{text}': {e}")


class SilenceModelingEngine:
    """
    Main engine for silence modeling and cultural timing control.
    
    This engine monitors user speech, classifies silence types, and controls
    when the agent should respond based on cultural timing rules.
    """
    
    def __init__(
        self,
        session: AgentSession,
        timing_rules: CulturalTimingRules,
    ):
        self.session = session
        self.rules = timing_rules
        self.state_machine = SilenceStateMachine(timing_rules)
        self.backchannel_manager = BackchannelManager(timing_rules.language, session)
        
        self._monitoring_task: Optional[asyncio.Task] = None
        self._is_monitoring = False
        self._response_blocked = False
        self._last_user_state = "listening"
        
        # Statistics
        self.stats = {
            "silence_events": [],
            "backchannels_triggered": 0,
            "response_delays": [],
        }
    
    async def start(self):
        """Start monitoring silence and controlling responses."""
        if self._is_monitoring:
            return
        
        self._is_monitoring = True
        self._setup_event_handlers()
        self._monitoring_task = asyncio.create_task(self._monitor_silence())
        logger.info(f"Silence Modeling Engine started (language: {self.rules.language})")
    
    async def stop(self):
        """Stop monitoring."""
        self._is_monitoring = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Silence Modeling Engine stopped")
    
    def _setup_event_handlers(self):
        """Set up event handlers for monitoring conversation state."""
        
        @self.session.on("user_state_changed")
        def on_user_state_changed(ev: UserStateChangedEvent):
            """Handle user state changes."""
            self._last_user_state = ev.new_state
            
            if ev.new_state == "listening":  # User stopped speaking
                asyncio.create_task(self._handle_silence_start())
            elif ev.new_state == "speaking":  # User started speaking
                self.state_machine.reset()
                self._response_blocked = False
        
        @self.session.on("user_input_transcribed")
        def on_user_input_transcribed(ev: UserInputTranscribedEvent):
            """Handle transcription events for timing."""
            if ev.transcript:
                timestamp = time.time()
                self.state_machine.update_transcription(ev.transcript, timestamp)
    
    async def _handle_silence_start(self):
        """Called when user stops speaking - apply cultural timing."""
        # Reset state machine
        self.state_machine.reset()
        self.state_machine.last_speech_time = time.time()
        
        # Monitoring is already running, no need to start a new task
    
    async def _monitor_silence(self):
        """Continuously monitor silence and classify it."""
        check_interval = 0.1  # Check every 100ms
        
        while self._is_monitoring:
            try:
                # Determine if user is currently speaking
                has_speech = self._last_user_state == "speaking"
                
                # Update state machine
                state, should_respond, should_backchannel = self.state_machine.update(
                    has_speech=has_speech
                )
                
                # Log silence event
                if state != "speaking":
                    self._log_silence_event(state, self.state_machine.silence_duration)
                
                # Handle backchannel
                if should_backchannel:
                    triggered = await self.backchannel_manager.trigger()
                    if triggered:
                        self.stats["backchannels_triggered"] += 1
                
                # Handle response timing
                if should_respond and not self._response_blocked:
                    # Cultural delay satisfied - allow response
                    response_delay = self.state_machine.silence_duration
                    self.stats["response_delays"].append(response_delay)
                    self._log_response_timing(response_delay)
                    # Response will proceed naturally through LiveKit's turn detection
                    # We just log and track the timing
                
                # Stop monitoring if user disengaged
                if state == "disengagement":
                    logger.info("User disengaged - stopping silence monitoring")
                    break
                
                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in silence monitoring: {e}")
                await asyncio.sleep(check_interval)
    
    def _log_silence_event(self, classification: str, duration: float):
        """Log a silence event."""
        event = {
            "timestamp": time.time(),
            "classification": classification,
            "duration": duration,
            "language": self.rules.language,
        }
        self.stats["silence_events"].append(event)
        
        # Keep only recent events (last 100)
        if len(self.stats["silence_events"]) > 100:
            self.stats["silence_events"] = self.stats["silence_events"][-100:]
        
        logger.debug(
            f"Silence: {duration:.2f}s, Type: {classification}, "
            f"Language: {self.rules.language}"
        )
    
    def _log_response_timing(self, response_delay: float):
        """Log response timing."""
        logger.info(
            f"Response timing: {response_delay:.2f}s delay "
            f"(target: {self.rules.min_response_delay:.2f}-{self.rules.max_response_delay:.2f}s, "
            f"language: {self.rules.language})"
        )
    
    def get_stats(self) -> dict:
        """Get statistics about silence modeling."""
        avg_response_delay = (
            sum(self.stats["response_delays"]) / len(self.stats["response_delays"])
            if self.stats["response_delays"]
            else 0.0
        )
        
        return {
            "language": self.rules.language,
            "total_silence_events": len(self.stats["silence_events"]),
            "backchannels_triggered": self.stats["backchannels_triggered"],
            "total_responses": len(self.stats["response_delays"]),
            "avg_response_delay": avg_response_delay,
            "recent_silence_events": self.stats["silence_events"][-10:],  # Last 10
        }


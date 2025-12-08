# Silence Modeling Engine - Integration Guide

This guide explains how to incorporate a **Silence Modeling Engine** into your LiveKit voice agent to handle culturally-aware silence detection and turn-taking.

## Architecture Overview

The Silence Modeling Engine should sit **between** LiveKit's built-in turn detection and your agent's response generation. It acts as a middleware layer that:

1. **Monitors** audio energy and ASR timing from LiveKit's VAD and STT
2. **Interprets** silence patterns based on cultural rules
3. **Controls** when the agent speaks by intercepting turn completion signals
4. **Triggers** backchannels at appropriate moments

## Integration Points

### 1. Event-Based Monitoring

LiveKit's `AgentSession` provides several events you can hook into:

```python
from livekit.agents import AgentSession, UserStateChangedEvent, AgentStateChangedEvent
from livekit.agents.voice import UserInputTranscribedEvent

# Monitor user state changes
@session.on("user_state_changed")
def on_user_state_changed(ev: UserStateChangedEvent):
    # Track when user starts/stops speaking
    # Use this to measure silence duration
    pass

# Monitor transcription events
@session.on("user_input_transcribed")
def on_user_input_transcribed(ev: UserInputTranscribedEvent):
    # Track ASR timing and partial transcripts
    # Use timestamps to measure silence gaps
    pass

# Monitor agent state
@session.on("agent_state_changed")
def on_agent_state_changed(ev: AgentStateChangedEvent):
    # Know when agent is listening/thinking/speaking
    # Control response timing based on this
    pass
```

### 2. Custom Turn Detection Wrapper

Instead of using `MultilingualModel()` directly, create a wrapper that adds cultural timing logic:

```python
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents import TurnDetection

class CulturalTurnDetection(TurnDetection):
    def __init__(self, language: str = "en"):
        self.base_detector = MultilingualModel()
        self.language = language
        self.timing_rules = self._get_timing_rules(language)
        self.silence_state = "none"  # none, pause, thinking, end_of_speech, disengagement
        self.last_speech_time = None
        self.silence_start_time = None
        
    def _get_timing_rules(self, language: str):
        if language.startswith("ja"):
            return {
                "min_response_delay": 0.2,  # 200ms
                "max_response_delay": 0.5,  # 500ms
                "long_silence_threshold": 2.0,  # 2 seconds
                "backchannel_frequency": "high",
                "allow_overlap": False,
            }
        else:  # English default
            return {
                "min_response_delay": 0.05,  # 50ms
                "max_response_delay": 0.15,  # 150ms
                "long_silence_threshold": 1.0,  # 1 second
                "backchannel_frequency": "low",
                "allow_overlap": True,
            }
```

### 3. Silence State Machine

Implement a state machine to distinguish silence types:

```python
class SilenceStateMachine:
    def __init__(self, timing_rules: dict):
        self.rules = timing_rules
        self.state = "none"
        self.silence_duration = 0.0
        self.last_audio_energy = 0.0
        self.asr_segments = []
        
    def update(self, audio_energy: float, asr_timestamp: float, has_speech: bool):
        """
        Update state based on audio energy and ASR data.
        
        Returns: (state, should_respond, should_backchannel)
        """
        current_time = time.time()
        
        if has_speech:
            self.state = "speaking"
            self.silence_duration = 0.0
            self.last_speech_time = current_time
            return ("speaking", False, False)
        
        # Calculate silence duration
        if self.last_speech_time:
            self.silence_duration = current_time - self.last_speech_time
        
        # Classify silence type
        if self.silence_duration < 0.3:
            self.state = "normal_pause"
            return ("normal_pause", False, False)
        elif self.silence_duration < self.rules["long_silence_threshold"]:
            self.state = "thinking"
            # Trigger soft backchannel for Japanese
            should_backchannel = (
                self.rules["backchannel_frequency"] == "high" and
                self.silence_duration > 0.5
            )
            return ("thinking", False, should_backchannel)
        elif self.silence_duration < 5.0:
            self.state = "end_of_speech"
            # Check if we should respond based on cultural timing
            min_delay = self.rules["min_response_delay"]
            max_delay = self.rules["max_response_delay"]
            if min_delay <= self.silence_duration <= max_delay:
                return ("end_of_speech", True, False)
            return ("end_of_speech", False, False)
        else:
            self.state = "disengagement"
            return ("disengagement", False, False)
```

### 4. Intercepting Turn Completion

You need to intercept when LiveKit's turn detector signals "turn complete" and apply your cultural delay:

```python
class CulturalAgentSession:
    def __init__(self, base_session: AgentSession, language: str):
        self.session = base_session
        self.silence_engine = SilenceStateMachine(self._get_timing_rules(language))
        self.pending_response = None
        self.response_timer = None
        
        # Wrap the session's turn detection
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        # Listen for when user stops speaking
        @self.session.on("user_state_changed")
        async def on_user_state(ev: UserStateChangedEvent):
            if ev.new_state == "listening":  # User stopped speaking
                # Don't immediately respond - apply cultural delay
                await self._handle_silence_start()
        
        # Monitor transcription for timing
        @self.session.on("user_input_transcribed")
        async def on_transcription(ev: UserInputTranscribedEvent):
            # Track ASR timing
            self.silence_engine.update_asr_segment(ev)
    
    async def _handle_silence_start(self):
        """Called when user stops speaking - apply cultural timing"""
        rules = self.silence_engine.rules
        
        # Start monitoring silence
        async def check_silence():
            while True:
                state, should_respond, should_backchannel = (
                    self.silence_engine.update(...)
                )
                
                if should_backchannel:
                    await self._trigger_backchannel()
                
                if should_respond:
                    # Cultural delay satisfied - allow response
                    await self._allow_response()
                    break
                
                if state == "disengagement":
                    # User disengaged - don't respond
                    break
                
                await asyncio.sleep(0.1)  # Check every 100ms
        
        asyncio.create_task(check_silence())
```

### 5. Audio Energy Monitoring

You'll need to access raw audio frames to measure energy. This requires hooking into the audio pipeline:

```python
from livekit.agents import PipelineNode

class AudioEnergyMonitor(PipelineNode):
    """Monitor audio energy levels for silence detection"""
    
    def __init__(self):
        self.energy_history = []
        self.current_energy = 0.0
    
    async def process(self, frame: AudioFrame) -> AudioFrame:
        # Calculate RMS energy
        samples = np.frombuffer(frame.data, dtype=np.int16)
        self.current_energy = np.sqrt(np.mean(samples**2))
        self.energy_history.append((time.time(), self.current_energy))
        
        # Keep only recent history (last 2 seconds)
        cutoff = time.time() - 2.0
        self.energy_history = [
            (t, e) for t, e in self.energy_history if t > cutoff
        ]
        
        return frame
    
    def get_current_energy(self) -> float:
        return self.current_energy
    
    def is_silent(self, threshold: float = 100.0) -> bool:
        return self.current_energy < threshold
```

### 6. Backchannel Generation

Implement backchannel triggers based on cultural rules:

```python
class BackchannelManager:
    def __init__(self, language: str, session: AgentSession):
        self.language = language
        self.session = session
        self.backchannels = self._get_backchannels(language)
        self.last_backchannel_time = 0.0
        self.min_backchannel_interval = 2.0  # Minimum 2 seconds between backchannels
    
    def _get_backchannels(self, language: str) -> list[str]:
        if language.startswith("ja"):
            return ["はい", "ええ", "そうですね", "なるほど"]
        else:
            return ["I see", "Okay", "Right", "Got it"]
    
    async def trigger(self):
        """Trigger a soft backchannel"""
        current_time = time.time()
        if current_time - self.last_backchannel_time < self.min_backchannel_interval:
            return  # Too soon for another backchannel
        
        backchannel = random.choice(self.backchannels)
        
        # For Japanese: softer, shorter
        # For English: can be slightly longer
        await self.session.say(
            backchannel,
            allow_interruptions=True,  # User can interrupt backchannel
        )
        
        self.last_backchannel_time = current_time
```

### 7. Preventing Unintentional Interruptions

Configure LiveKit's interruption handling based on culture:

```python
session = AgentSession(
    # ... other config ...
    allow_interruptions=True,  # Always allow, but control timing
    min_interruption_duration=0.5,  # Minimum speech to interrupt
    min_interruption_words=1,  # At least one word
    false_interruption_timeout=2.0,  # Wait 2s before resuming
    resume_false_interruption=True,  # Resume if false interruption
)
```

For Japanese (no overlap):
- Set `min_interruption_duration` higher (0.8-1.0s)
- Be more conservative about resuming after interruption

For English (slight overlap OK):
- Lower `min_interruption_duration` (0.3-0.5s)
- More tolerant of brief interruptions

## Configuration Structure

Create a configuration class to manage cultural timing rules:

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class CulturalTimingRules:
    language: str
    min_response_delay: float  # seconds
    max_response_delay: float  # seconds
    long_silence_threshold: float  # seconds
    backchannel_frequency: Literal["low", "medium", "high"]
    backchannel_interval: float  # minimum seconds between backchannels
    allow_overlap: bool
    min_interruption_duration: float
    silence_classification_thresholds: dict[str, float]  # thresholds for each silence type

# Default configurations
JAPANESE_RULES = CulturalTimingRules(
    language="ja-JP",
    min_response_delay=0.2,
    max_response_delay=0.5,
    long_silence_threshold=2.0,
    backchannel_frequency="high",
    backchannel_interval=2.0,
    allow_overlap=False,
    min_interruption_duration=0.8,
    silence_classification_thresholds={
        "normal_pause": 0.3,
        "thinking": 1.0,
        "end_of_speech": 2.0,
        "disengagement": 5.0,
    }
)

ENGLISH_RULES = CulturalTimingRules(
    language="en-US",
    min_response_delay=0.05,
    max_response_delay=0.15,
    long_silence_threshold=1.0,
    backchannel_frequency="low",
    backchannel_interval=3.0,
    allow_overlap=True,
    min_interruption_duration=0.3,
    silence_classification_thresholds={
        "normal_pause": 0.2,
        "thinking": 0.5,
        "end_of_speech": 1.0,
        "disengagement": 3.0,
    }
)
```

## Integration with Your Current Code

Here's how to modify your existing `agent.py`:

```python
# 1. Add silence modeling imports
from silence_modeling import SilenceModelingEngine, CulturalTimingRules

# 2. Determine language from Call Pack or context
language = "ja-JP"  # or "en-US" - get from your Call Pack

# 3. Create cultural timing rules
timing_rules = (
    CulturalTimingRules.japanese() 
    if language.startswith("ja") 
    else CulturalTimingRules.english()
)

# 4. Wrap your session with silence modeling
session = AgentSession(
    stt="assemblyai/universal-streaming:en",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
    vad=silero.VAD.load(),
    turn_detection=MultilingualModel(),
    # Configure based on culture
    min_endpointing_delay=timing_rules.min_response_delay,
    allow_interruptions=timing_rules.allow_overlap,
    min_interruption_duration=timing_rules.min_interruption_duration,
)

# 5. Add silence modeling engine
silence_engine = SilenceModelingEngine(
    session=session,
    timing_rules=timing_rules,
)

await session.start(
    room=ctx.room,
    agent=Assistant(),
    room_options=room_io.RoomOptions(...),
)

# 6. Start silence monitoring
await silence_engine.start()
```

## Key Implementation Considerations

### 1. **Audio Energy Access**
- You may need to add a custom pipeline node to access raw audio frames
- Alternatively, use VAD output as a proxy for audio energy
- Consider using LiveKit's built-in audio processing hooks

### 2. **ASR Timing**
- Use `user_input_transcribed` events to track transcription timestamps
- Compare timestamps between segments to measure silence gaps
- Partial transcripts can help detect "thinking" pauses

### 3. **Turn Detection Integration**
- The `MultilingualModel` already provides turn detection
- Your silence engine should **delay** the response, not replace turn detection
- Use `min_endpointing_delay` parameter to set minimum wait time

### 4. **State Management**
- Track silence state across the conversation
- Reset state when user speaks again
- Handle edge cases (disconnections, long pauses)

### 5. **Backchannel Implementation**
- Use `session.say()` with short phrases for backchannels
- Set `allow_interruptions=True` so user can continue
- Don't add backchannels to conversation history (they're not "turns")

### 6. **Testing & Tuning**
- Log all silence durations and classifications
- Measure actual response delays vs. target delays
- A/B test different timing rules
- Use LiveKit's observability tools to monitor performance

## Logging Requirements

As specified in your README, log:
- Silence durations
- Response timing
- Turn-taking behavior
- Template usage
- Rule-based response triggers

```python
import logging

logger = logging.getLogger("silence_modeling")

def log_silence_event(
    silence_duration: float,
    classification: str,
    cultural_rules: CulturalTimingRules,
    response_delay: float,
):
    logger.info(
        f"Silence: {silence_duration:.2f}s, "
        f"Type: {classification}, "
        f"Language: {cultural_rules.language}, "
        f"ResponseDelay: {response_delay:.2f}s"
    )
```

## Next Steps

1. **Create the Silence Modeling Engine module** with the classes outlined above
2. **Integrate with your Call Pack** to determine language/culture
3. **Add audio energy monitoring** via pipeline nodes or VAD callbacks
4. **Implement the state machine** for silence classification
5. **Test with both Japanese and English** conversations
6. **Tune timing thresholds** based on real conversation data
7. **Add comprehensive logging** for observability

This architecture allows you to layer cultural intelligence on top of LiveKit's robust turn detection, giving you fine-grained control over silence interpretation and response timing.


# Conversational Design Configuration Guide

This document explains all conversational design parameters available for `AgentSession` in LiveKit Agents, including their purpose, default values, and recommended settings for different languages.

## Table of Contents

- [Turn Detection Options](#turn-detection-options)
- [Interruption Parameters](#interruption-parameters)
- [Endpointing/Timing Parameters](#endpointingtiming-parameters)
- [User State Management](#user-state-management)
- [Tool Call Parameters](#tool-call-parameters)
- [Preemptive Generation](#preemptive-generation)
- [TTS Text Processing](#tts-text-processing)
- [IVR Detection](#ivr-detection)
- [Language-Specific Recommendations](#language-specific-recommendations)

---

## Turn Detection Options

### `turn_detection`

**Type:** `TurnDetectionMode | None`  
**Default:** `None` (auto-select)  
**Options:**
- `None` - Auto-selects the best available mode (priority: `realtime_llm` → `vad` → `stt` → `manual`)
- `MultilingualModel()` - Custom turn detector model for context-aware turn detection (recommended)
- `"vad"` - Voice Activity Detection only (works with any language)
- `"stt"` - STT endpointing (uses phrase endpoints from STT provider)
- `"realtime_llm"` - Built-in turn detection from realtime models (OpenAI Realtime API, Gemini Live)
- `"manual"` - Manual turn control (disable automatic detection)

**Description:**  
Determines how the agent detects when the user has finished speaking. The turn detector model (`MultilingualModel`) is recommended for most use cases as it provides context-aware turn detection that understands conversation flow better than simple silence detection.

**When to use:**
- **Turn detector model**: Best for natural conversations, supports multiple languages
- **VAD only**: Good for languages not well-supported by turn detector, or when you need simple silence-based detection
- **STT endpointing**: Use when your STT provider has sophisticated endpointing (e.g., AssemblyAI)
- **Realtime models**: Use when using OpenAI Realtime API or Gemini Live (most cost-effective)
- **Manual**: Use for push-to-talk interfaces or when you need full control

---

## Interruption Parameters

### `allow_interruptions`

**Type:** `bool`  
**Default:** `True`

**Description:**  
Whether the user can interrupt the agent mid-utterance. When `True`, the agent will pause speaking when it detects user speech. Ignored when using a realtime model with built-in turn detection.

**Recommendations:**
- **Japanese**: `True` (but use higher `min_interruption_duration` for cultural appropriateness)
- **English**: `True` (more natural for conversational flow)

---

### `discard_audio_if_uninterruptible`

**Type:** `bool`  
**Default:** `True`

**Description:**  
When `True`, buffered audio is dropped while the agent is speaking and cannot be interrupted. This prevents audio from queuing up during uninterruptible speech segments.

**Recommendations:**
- Keep as `True` for most use cases to prevent audio backlog

---

### `min_interruption_duration`

**Type:** `float` (seconds)  
**Default:** `0.5`

**Description:**  
Minimum detected speech duration (in seconds) before triggering an interruption. Higher values require longer user speech to interrupt, reducing false interruptions from background noise or brief sounds.

**Recommendations:**
- **Japanese**: `0.8` - More conservative, prevents accidental interruptions
- **English**: `0.3` - More responsive, allows quicker interruptions
- **Noisy environments**: `0.6-0.8` - Higher threshold to reduce false positives

---

### `min_interruption_words`

**Type:** `int`  
**Default:** `0`

**Description:**  
Minimum number of words required to consider an interruption. Only used if STT is enabled. Setting this to `1` or `2` helps filter out false interruptions from non-speech sounds.

**Recommendations:**
- **Japanese**: `2` - Requires at least 2 words (more conservative)
- **English**: `1` - Single word can interrupt (more responsive)
- **High noise environments**: `2-3` - Reduces false interruptions

---

### `false_interruption_timeout`

**Type:** `float | None` (seconds)  
**Default:** `2.0`

**Description:**  
Time to wait (in seconds) before signaling a false interruption. If no transcribed speech is generated during this period, an `agent_false_interruption` event is emitted and the agent resumes speaking if `resume_false_interruption` is `True`. Set to `None` to disable false interruption handling.

**Recommendations:**
- **Japanese**: `2.5` - Longer timeout for more conservative handling
- **English**: `2.0` - Standard timeout
- **Fast-paced conversations**: `1.5` - Quicker recovery
- **Disable**: `None` - If you want to treat all interruptions as intentional

---

### `resume_false_interruption`

**Type:** `bool`  
**Default:** `True`

**Description:**  
Whether to resume speech output after a false interruption. When `True`, the agent continues speaking from where it left off after `false_interruption_timeout` if no user transcription is generated.

**Recommendations:**
- Keep as `True` for better user experience (agent recovers from false interruptions)
- Set to `False` if you want interruptions to always stop the agent

---

## Endpointing/Timing Parameters

### `min_endpointing_delay`

**Type:** `float` (seconds)  
**Default:** `0.5`

**Description:**  
Minimum time the agent must wait after a potential end-of-utterance signal (from VAD or turn detector) before declaring the user's turn complete. This delay helps ensure the user has actually finished speaking and isn't just pausing mid-sentence.

**Recommendations:**
- **Japanese**: `0.2` - Slightly longer delay for cultural appropriateness (allows for longer pauses)
- **English**: `0.05` - Quick response, minimal delay
- **Formal/conservative**: `0.3-0.5` - More cautious
- **Fast-paced**: `0.05-0.1` - Very responsive

**Cultural Note:**  
Japanese conversations typically have longer pauses between turns, so a slightly higher delay is more natural. English speakers tend to have shorter pauses and may overlap slightly.

---

### `max_endpointing_delay`

**Type:** `float` (seconds)  
**Default:** `3.0`

**Description:**  
Maximum time to wait for the user to speak after the turn detector model indicates the user is likely to continue speaking. This parameter only has effect when using the turn detector model. If the user doesn't speak within this time, the turn is considered complete.

**Recommendations:**
- **Japanese**: `4.0` - Longer max delay to accommodate longer thinking pauses
- **English**: `3.0` - Standard delay
- **Quick responses**: `2.0-2.5` - Faster turn completion
- **Patient/conversational**: `4.0-5.0` - Allows for longer pauses

---

### `min_consecutive_speech_delay`

**Type:** `float` (seconds)  
**Default:** `0.0`

**Description:**  
Minimum delay between consecutive speech segments from the agent. This can help create more natural pacing in agent responses, especially for longer multi-part responses.

**Recommendations:**
- **Japanese**: `0.1` - Small delay between speech segments for natural pacing
- **English**: `0.0` - No delay needed
- **Formal presentations**: `0.2-0.3` - More deliberate pacing
- **Conversational**: `0.0` - Natural flow

---

## User State Management

### `user_away_timeout`

**Type:** `float | None` (seconds)  
**Default:** `15.0`

**Description:**  
If set, marks the user state as "away" after this amount of time when both user and agent are silent. Set to `None` to disable user away detection.

**Recommendations:**
- **Standard**: `15.0` - Good default for most use cases
- **Short sessions**: `10.0` - Quicker timeout for brief interactions
- **Long sessions**: `30.0` - Longer timeout for extended conversations
- **Disable**: `None` - If you don't need away state tracking

**Use Cases:**
- Detect when user has left or disconnected
- Trigger re-engagement prompts
- Clean up resources after inactivity

---

## Tool Call Parameters

### `max_tool_steps`

**Type:** `int`  
**Default:** `3`

**Description:**  
Maximum number of consecutive tool calls per LLM turn. This limits how many tools the agent can call in sequence before requiring user input or generating a response.

**Recommendations:**
- **Simple tasks**: `1-2` - Fewer tool calls, simpler workflows
- **Standard**: `3` - Good balance for most use cases
- **Complex workflows**: `5-10` - Allow multi-step tool orchestration
- **Unlimited**: Set high (e.g., `20`) if you need complex multi-step operations

**Note:**  
Higher values allow more complex tool orchestration but may lead to longer response times and higher costs.

---

## Preemptive Generation

### `preemptive_generation`

**Type:** `bool`  
**Default:** `False`

**Description:**  
Whether to speculatively begin LLM and TTS requests before an end-of-turn is detected. When `True`, the agent sends inference calls as soon as a user transcript is received rather than waiting for a definitive turn boundary. This can reduce response latency but may incur extra compute if the user interrupts or revises mid-utterance.

**Recommendations:**
- **Latency-sensitive**: `True` - Reduces perceived response delay
- **Cost-sensitive**: `False` - Avoids wasted compute on interrupted turns
- **Standard**: `False` - Default is usually best unless latency is critical

**Trade-offs:**
- ✅ **Pros**: Lower latency, faster responses
- ❌ **Cons**: Higher compute costs if user interrupts frequently, may generate responses to incomplete thoughts

**Best for:**
- Real-time conversations where speed is critical
- Scenarios where interruptions are rare
- When STT returns final transcripts faster than VAD detects end-of-speech

---

## TTS Text Processing

### `tts_text_transforms`

**Type:** `list[str] | None`  
**Default:** `None` (uses defaults: `["filter_markdown", "filter_emoji"]`)

**Description:**  
Transforms to apply to TTS input text before synthesis. Available built-in transforms:
- `"filter_markdown"` - Removes markdown formatting (e.g., `**bold**`, `*italic*`)
- `"filter_emoji"` - Removes emoji characters

**Options:**
- `None` - Use default transforms (filters markdown and emoji)
- `[]` - Disable all transforms
- `["filter_markdown"]` - Only filter markdown
- `["filter_emoji"]` - Only filter emoji
- `["filter_markdown", "filter_emoji"]` - Filter both (default)

**Recommendations:**
- **Standard**: `None` - Use defaults (filters markdown and emoji)
- **Preserve formatting**: `[]` - If you want to keep markdown/emoji (may cause TTS issues)
- **Custom**: Specify only the transforms you need

**Note:**  
Most TTS engines don't handle markdown or emoji well, so filtering is usually recommended.

---

## IVR Detection

### `ivr_detection`

**Type:** `bool`  
**Default:** `False`

**Description:**  
Whether to detect if the agent is interacting with an IVR (Interactive Voice Response) system. When enabled, the agent can detect IVR prompts and respond appropriately.

**Recommendations:**
- **Standard voice agents**: `False` - Not needed for direct user conversations
- **IVR integration**: `True` - Enable when agent needs to interact with phone systems
- **Call center scenarios**: `True` - Useful for automated call handling

**Use Cases:**
- Automated phone systems
- Call routing and handling
- Integration with existing IVR infrastructure

---

## Language-Specific Recommendations

### Japanese (`ja`, `ja-JP`)

Japanese conversations have distinct characteristics:
- **Longer pauses** between turns
- **Less overlap** - speakers typically wait for complete silence
- **More conservative** interruption patterns
- **Higher formality** in many contexts

**Recommended Configuration:**
```python
turn_detection=MultilingualModel()
allow_interruptions=True
min_interruption_duration=0.8  # Longer duration
min_interruption_words=2  # Require 2 words
false_interruption_timeout=2.5  # Longer timeout
min_endpointing_delay=0.2  # Slightly longer delay
max_endpointing_delay=4.0  # Longer max delay
min_consecutive_speech_delay=0.1  # Small delay between segments
```

### English (`en`, `en-US`)

English conversations are typically:
- **Faster turn-taking** with shorter pauses
- **More tolerant of overlap** - slight overlap is natural
- **More responsive** to interruptions
- **Quicker responses** expected

**Recommended Configuration:**
```python
turn_detection=MultilingualModel()
allow_interruptions=True
min_interruption_duration=0.3  # Shorter, more responsive
min_interruption_words=1  # Single word can interrupt
false_interruption_timeout=2.0  # Standard timeout
min_endpointing_delay=0.05  # Quick response
max_endpointing_delay=3.0  # Standard delay
min_consecutive_speech_delay=0.0  # No delay needed
```

### Other Languages

For languages not specifically configured:
- Start with **English-like settings** as a baseline
- Adjust `min_endpointing_delay` based on typical pause lengths in the language
- Consider cultural norms around turn-taking and interruptions
- Test and iterate based on user feedback

---

## Configuration Examples

### Conservative Configuration (Formal, Patient)
```python
session = AgentSession(
    turn_detection=MultilingualModel(),
    allow_interruptions=True,
    min_interruption_duration=0.8,
    min_interruption_words=2,
    false_interruption_timeout=3.0,
    resume_false_interruption=True,
    min_endpointing_delay=0.3,
    max_endpointing_delay=4.0,
    min_consecutive_speech_delay=0.2,
    user_away_timeout=20.0,
    preemptive_generation=False,
)
```

### Responsive Configuration (Fast-Paced, Conversational)
```python
session = AgentSession(
    turn_detection=MultilingualModel(),
    allow_interruptions=True,
    min_interruption_duration=0.3,
    min_interruption_words=1,
    false_interruption_timeout=1.5,
    resume_false_interruption=True,
    min_endpointing_delay=0.05,
    max_endpointing_delay=2.5,
    min_consecutive_speech_delay=0.0,
    user_away_timeout=10.0,
    preemptive_generation=True,  # Enable for lower latency
)
```

### Manual Control Configuration (Push-to-Talk)
```python
session = AgentSession(
    turn_detection="manual",  # Manual control
    allow_interruptions=True,
    # Other parameters less relevant for manual mode
)
```

---

## Using the Configuration Model

The `model.py` file provides a convenient way to get language-appropriate configurations:

```python
from model import get_conversational_config

# Get configuration for Japanese
config = get_conversational_config(
    language="ja-JP",
    use_turn_detector=True,
    preemptive_generation=False,
    user_away_timeout=15.0,
)

# Use in AgentSession
session = AgentSession(
    stt=stt,
    llm=llm,
    tts=tts,
    vad=vad,
    **config.to_dict(),
)
```

---

## Testing and Tuning

### Key Metrics to Monitor

1. **Response Latency** - Time from user speech end to agent response start
2. **False Interruption Rate** - How often interruptions are false positives
3. **Turn Completion Accuracy** - Whether agent responds at appropriate times
4. **User Satisfaction** - Subjective feedback on conversation flow

### Tuning Process

1. **Start with defaults** for your language
2. **Monitor metrics** using LiveKit observability
3. **Adjust incrementally** - Change one parameter at a time
4. **Test with real users** - Get feedback on conversation flow
5. **Iterate** based on data and feedback

### Common Adjustments

- **Too many false interruptions**: Increase `min_interruption_duration` or `min_interruption_words`
- **Agent responds too quickly**: Increase `min_endpointing_delay`
- **Agent waits too long**: Decrease `max_endpointing_delay`
- **Conversation feels slow**: Enable `preemptive_generation` or decrease delays
- **Too many tool calls**: Decrease `max_tool_steps`

---

## Backchannel Handling

### Overview

Backchannels are short words or phrases (like "uh-huh", "yeah", "I see", "はい") that users say to show they're listening without actually interrupting. By default, these can trigger interruptions, causing the agent to stop speaking unnecessarily.

### Built-in Options

**LiveKit Agents does not have a built-in parameter to configure backchannel words.** However, you have several options:

#### 1. Use `min_interruption_words`

Setting `min_interruption_words=2` or higher helps filter out single-word backchannels, but this is not specific to backchannels and may also filter legitimate short interruptions.

```python
session = AgentSession(
    min_interruption_words=2,  # Require at least 2 words
    # ... other config
)
```

#### 2. Use Realtime LLM Models

Realtime models like **OpenAI Realtime API** with **Semantic VAD** have better semantic understanding and may better distinguish backchannels from real interruptions:

```python
from livekit.plugins.openai import realtime
from openai.types.beta.realtime.session import TurnDetection

session = AgentSession(
    llm=realtime.RealtimeModel(
        turn_detection=TurnDetection(
            type="semantic_vad",  # Better at detecting backchannels
            eagerness="auto",
        )
    ),
)
```

**Note:** Semantic VAD doesn't explicitly detect backchannels, but it's generally better at understanding context and may be less likely to treat backchannels as interruptions.

#### 3. Custom Backchannel Filtering (Recommended)

Implement custom event handlers to filter backchannels. Use the `backchannel_filter.py` module:

```python
from backchannel_filter import setup_backchannel_filtering

# After creating session
session = AgentSession(...)

# Set up backchannel filtering
backchannel_filter = setup_backchannel_filtering(
    session,
    language="en-US",  # or "ja-JP"
    prevent_interruption=True,
)
```

**How it works:**
- Monitors `user_input_transcribed` events
- Detects common backchannel words/phrases
- Logs backchannels for monitoring
- Works with `min_interruption_words` to reduce false interruptions

**Supported Languages:**
- English: "uh-huh", "yeah", "mm-hmm", "okay", "right", "I see", etc.
- Japanese: "はい", "ええ", "そうですね", "なるほど", etc.

**Limitations:**
- Cannot directly prevent interruptions (LiveKit's interruption logic runs before event handlers)
- Works best when combined with `min_interruption_words=2` or higher
- Backchannels are logged but may still trigger brief pauses

### Best Practices

1. **Combine approaches**: Use `min_interruption_words=2` + backchannel filtering + appropriate `min_interruption_duration`
2. **Language-specific**: Different languages have different backchannel patterns
3. **Monitor logs**: Check backchannel detection logs to tune your configuration
4. **Test with real users**: Backchannel behavior varies by individual and context

### Example Configuration

```python
from model import get_conversational_config
from backchannel_filter import setup_backchannel_filtering

language = "en-US"

# Get conversational config
config = get_conversational_config(
    language,
    use_turn_detector=True,
)

# Create session with higher min_interruption_words to filter backchannels
session = AgentSession(
    stt=stt,
    llm=llm,
    tts=tts,
    vad=vad,
    min_interruption_words=2,  # Filter single-word backchannels
    **config.to_dict(),
)

# Set up backchannel filtering
setup_backchannel_filtering(session, language=language)
```

---

## Additional Resources

- [LiveKit Agents Documentation - Turn Detection](https://docs.livekit.io/agents/build/turns/)
- [LiveKit Agents Documentation - AgentSession](https://docs.livekit.io/reference/python/v1/livekit/agents/voice/index.html#livekit.agents.voice.AgentSession)
- [Voice AI Quickstart](https://docs.livekit.io/agents/start/voice-ai/)

---

*Last updated: Based on LiveKit Agents v1.2*


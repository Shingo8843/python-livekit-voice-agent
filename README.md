# Python LiveKit Voice Agent

A multilingual voice AI agent built on LiveKit Agents framework, designed for delivery appointment scheduling and logistics coordination. The agent supports English and Japanese with culturally-appropriate conversational behaviors.

---

## What This Agent Does

This voice agent handles **outbound phone calls for delivery appointment management**. It can:

- **Schedule new delivery appointments** - Propose delivery dates and time windows, confirm availability
- **Modify existing appointments** - Change delivery times within allowed windows
- **Cancel appointments** - Handle cancellation requests with confirmation
- **Confirm appointments** - Verify scheduled delivery details

The agent is designed to work with receiving departments managing logistics coordination calls with a professional, friendly tone.

---

## Currently Implemented

### Core Infrastructure ✅

1. **LiveKit Agent Framework**

   - Full integration with LiveKit Agents SDK
   - AgentServer and AgentSession setup
   - Real-time audio streaming and processing
   - Room I/O with noise cancellation support

2. **Speech Services Integration**

   - **STT (Speech-to-Text)**: Deepgram with language-specific models
     - English: `flux-general-en` model
     - Japanese: `nova-general-ja` model
   - **LLM**: OpenAI GPT-4.1 for conversation generation
   - **TTS (Text-to-Speech)**: Cartesia Sonic-3 with language-specific voices
     - Configurable speed, volume, and emotion parameters
   - **VAD (Voice Activity Detection)**: Silero VAD for speech detection

3. **Language Support**

   - **English (en-US)**: Full support with optimized conversational parameters
   - **Japanese (ja-JP)**: Full support with culturally-appropriate timing

4. **Template-Based Prompting System**

   - Language-specific prompt files (`prompt_en.txt`, `prompt_ja.txt`)
   - Variable injection from JSON configuration (`prompt_variables.json`)
   - Dynamic variable substitution (e.g., `{{delivery_date}}`, `{{agent_name}}`)
   - Supports delivery appointment workflows with detailed instructions

5. **Cultural Conversational Configuration**

   - Language-specific turn detection and timing parameters
   - **Japanese settings**:
     - Longer interruption duration (0.8s)
     - More conservative endpointing delays (0.2-4.0s)
     - Requires 2+ words for interruption
   - **English settings**:
     - Faster response times (0.05-3.0s)
     - More responsive interruptions (0.3s, 1 word)
   - Multilingual turn detector model for context-aware turn detection

6. **Function Tools**

   - `get_current_time()` - Provides current date and time
   - `search_knowledge_base()` - Placeholder for knowledge base queries
   - `hang_up()` - Gracefully ends calls with goodbye messages

7. **Configuration Management**

   - Environment variable support (`.env.local`)
   - Configurable TTS parameters (speed, volume, emotion)
   - Language selection via `AGENT_LANGUAGE` environment variable
   - Optional preemptive generation and user away timeout

8. **Noise Cancellation**
   - Automatic noise cancellation for telephony calls (BVCTelephony)
   - Standard noise cancellation for regular participants (BVC)

---

## What It Does NOT Do Yet (Future Implementation)

The following features are planned but not yet implemented:

### 1. Call Pack Data Model ❌

- **Status**: Not implemented
- **Planned**: Structured data model to preprocess and store all call variables before the call begins
- **Example structure**:
  ```json
  {
    "language": "ja-JP",
    "orderId": "59127",
    "deliveryDate": "2024-01-15",
    "windowStart": "09:00",
    "windowEnd": "17:00",
    "poNumber": "PO-12345",
    "palletCount": 5,
    "truckType": "box truck"
  }
  ```

### 2. Call Scheduler ❌

- **Status**: Not implemented
- **Planned**: Automated call scheduling and retry logic
- **Features**:
  - Up to 3 retry attempts
  - 1 hour delay between attempts
  - Voicemail detection via energy pattern analysis
  - Business hours enforcement
  - Attempt logging with timestamps

### 3. Advanced Silence Modeling Engine ❌

- **Status**: Partially implemented (basic timing parameters exist)
- **Planned**: Sophisticated silence analysis
- **Features**:
  - Distinguish between normal pauses, thinking, end of speech, disengagement
  - Context-aware silence interpretation
  - Automatic backchannel generation
  - Prevent unintentional interruptions

### 4. Cultural Intelligence Layer ❌

- **Status**: Partially implemented (TTS emotion settings exist)
- **Planned**: Advanced prosody and pacing adjustments
- **Features**:
  - Text transformation before TTS
  - Natural pause insertion
  - Culturally-appropriate intonation patterns
  - Sentence ending modifications
  - Acknowledgement phrase insertion

### 5. Structured Call Logging and Post-Call Output ❌

- **Status**: Not implemented
- **Planned**: Comprehensive call analytics
- **Features**:
  - Final transcript generation
  - Structured call summary (JSON format)
  - Extracted conversation variables
  - Call status records (success, no answer, voicemail, etc.)
  - Storage integration (S3 or database)
  - 90-day log retention
  - Call ID and Order ID as primary keys

### 6. Conversation State Machine ❌

- **Status**: Not implemented
- **Planned**: Explicit state management for call flow
- **States**:
  - Call Initiated
  - Introduction Delivered
  - Information Presented
  - Awaiting Response
  - Handling Questions
  - Confirming Next Steps
  - Closing
  - Ending Call

### 7. Template-Based Conversation Flow ❌

- **Status**: Partially implemented (prompt templates exist, but not strict flow control)
- **Planned**: Strict template-based conversation with fixed scripts
- **Features**:
  - Introduction template
  - Information delivery template
  - Confirmation request template
  - Clarification templates
  - Closing template
  - Error fallback templates

### 8. Advanced Observability ❌

- **Status**: Basic logging exists
- **Planned**: Comprehensive metrics and monitoring
- **Features**:
  - Silence duration tracking
  - Response timing metrics
  - Turn-taking behavior analysis
  - Template usage statistics
  - Rule-based response trigger logging
  - Performance dashboards

---

## Technical Architecture

### Current Stack

- **Framework**: LiveKit Agents SDK v1.2+
- **Python**: 3.12 or 3.13 (3.14 not supported due to dependency limitations)
- **STT**: Deepgram (flux-general-en, nova-general-ja)
- **LLM**: OpenAI GPT-4.1
- **TTS**: Cartesia Sonic-3
- **VAD**: Silero
- **Noise Cancellation**: BVC/BVCTelephony

### Project Structure

```
livekit-voice-agent/
├── agent.py              # Main agent server and session setup
├── model.py              # Conversational configuration models
├── tools.py              # Function tools for the agent
├── prompt_en.txt        # English prompt template
├── prompt_ja.txt        # Japanese prompt template
├── prompt_variables.json # Variable substitution data
├── pyproject.toml       # Project dependencies
└── CONVERSATIONAL_CONFIG.md # Detailed configuration guide
```

---

## Setup and Configuration

### Prerequisites

1. Python 3.12 or 3.13 (3.14 is not supported due to `livekit-blingfire` dependency limitations)
2. LiveKit account and credentials
3. API keys for:
   - Deepgram (STT)
   - OpenAI (LLM)
   - Cartesia (TTS)

### Installation

```bash
# Install dependencies
pip install -e .

# Or using uv
uv pip install -e .
```

### Environment Variables

Create a `.env.local` file with:

```env
# Required
DEEPGRAM_API_KEY=your_deepgram_key
OPENAI_API_KEY=your_openai_key
CARTESIA_API_KEY=your_cartesia_key

# Optional
AGENT_LANGUAGE=en-US  # or ja-JP
TTS_SPEED=1.0
TTS_VOLUME=1.0
TTS_EMOTION=friendly  # or calm for Japanese
PREEMPTIVE_GENERATION=false
USER_AWAY_TIMEOUT=15.0
```

### Running the Agent

```bash
# Using LiveKit CLI
livekit-agents dev

# Or directly
python -m livekit_voice_agent.agent
```

---

## Configuration Details

### Conversational Parameters

The agent uses language-specific conversational configurations that control:

- **Turn Detection**: Multilingual model for context-aware turn detection
- **Interruption Handling**: Duration and word count thresholds
- **Endpointing**: Minimum/maximum delays before responding
- **User State**: Away timeout detection
- **Tool Calls**: Maximum tool execution steps

See `CONVERSATIONAL_CONFIG.md` for detailed parameter documentation.

### Prompt Variables

Edit `prompt_variables.json` to customize:

- Carrier brand name
- Logistics company name
- Agent name
- Store name
- Delivery dates and times
- PO numbers, pallet counts, truck types

Variables are automatically injected into prompt templates using `{{variable_name}}` syntax.

---

## Future Roadmap

### Phase 1: Core Operational Features

- [ ] Implement Call Pack data model
- [ ] Build rule-based response layer
- [ ] Add conversation state machine

### Phase 2: Call Management

- [ ] Implement call scheduler with retry logic
- [ ] Add voicemail detection
- [ ] Business hours enforcement

### Phase 3: Advanced Intelligence

- [ ] Enhanced silence modeling engine
- [ ] Full cultural intelligence layer
- [ ] Template-based conversation flow control

### Phase 4: Analytics and Observability

- [ ] Structured call logging
- [ ] Post-call summary generation
- [ ] Performance metrics and dashboards
- [ ] Storage integration (S3/database)

---

## Contributing

This project is actively under development. Contributions are welcome for:

- Implementing planned features
- Improving cultural conversational behaviors
- Adding support for additional languages
- Enhancing error handling and reliability

---

## License

[Add your license information here]

---

## References

- [LiveKit Agents Documentation](https://docs.livekit.io/agents/)
- [LiveKit Conversational Design Guide](https://docs.livekit.io/agents/conversational-design/)
- [Deepgram API Documentation](https://developers.deepgram.com/)
- [Cartesia API Documentation](https://docs.cartesia.ai/)

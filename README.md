1. High-Level Architecture

The system is composed of the following modules:

LiveKit Transport Layer
Manages calls, audio streams, playback, connection, and termination signals.

Conversation Engine
Controls call flow, manages turn-taking, silence interpretation, and step progression.

Template Prompting + Variable Injection Layer
Inserts operational variables into fixed conversation templates.
Ensures deterministic responses and predictable agent behavior.

Rule-Based Response Layer
Handles operational questions such as quantity, damage, or shipment status.
Avoids relying on general LLM reasoning.

Cultural Intelligence Layer
Adjusts prosody, timing, silence tolerance, backchannel frequency, and pacing.

ASR / LLM / TTS Services
Provides streaming transcription, constrained text generation, and audio output.

Call Scheduler
Defines retry logic, business hour rules, and voicemail detection.

Logging and Post-Call Output
Creates final transcripts and a structured call summary.

No translation module is included.

2. Data Model: Call Pack

All operational input is preprocessed before the call begins.
The system extracts and stores the variables needed for the entire call.

Call Pack Example

{
  language: "ja-JP",
  orderId: "59127",
  productName: "PowerCraft Pro 300",
  cartons: 4,
  pickupTime: "16:00",
  damageDescription: "2 cm dent on the corner",
  requiresShipmentConfirmation: true
}


The Call Pack is stable and immutable during the call.

3. Template-Based Prompting Model

The entire conversation uses predefined templates:

Introduction template

Information delivery template

Confirmation request template

Clarification templates

Closing template

Error fallback templates

Variables from the Call Pack are injected into slots in the templates.

Technical Goals

Reduce LLM creativity

Ensure predictable operational output

Prevent hallucination

Maintain consistent tone and politeness

Speed up response generation

Only short, controlled text blocks are generated during the call.

4. Conversation Engine

The Conversation Engine is the orchestrator, controlling:

Call flow state

Turn-taking

Silence analysis

Backchannel generation

Determining when to speak or wait

Handing off queries to the rule-based layer

Injecting template output into TTS

Conversation States

Call Initiated

Introduction Delivered

Information Presented

Awaiting Response

Handling Questions

Confirming Next Steps

Closing

Ending Call

State transitions are predictable because the script is fixed.

5. Silence Modeling Engine

Even with templates, silence behavior must reflect the target culture.

Responsibilities

Monitor audio energy and ASR timing to detect silence

Distinguish between:

normal pause

thinking

end of speech

disengagement

Control when the agent speaks

Trigger supportive backchannels

Prevent unintentional interruptions

Cultural Timing Rules

Japanese

Minimum delay before responding: 200–500 ms

Long silences tolerated

Backchannels frequent but soft

No immediate overlap

English

Minimum delay: 50–150 ms

Silences are minimized

Backchannels less frequent

Slight overlap acceptable

The timing rules are configurable but follow these defaults.

6. Cultural Intelligence Layer

This layer transforms text before sending it to TTS.

Adaptations

Adjust pacing

Modify sentence endings

Insert natural pauses

Smooth intonation patterns

Add culturally appropriate acknowledgement phrases

Ensure no English-style stress appears in Japanese speech

Ensure no overly indirect phrasing appears in English speech

This layer does not change the meaning, only the delivery.

7. Rule-Based Response Layer

The system must answer real questions reliably without relying on LLM reasoning.

Example rules

If user asks about carton quantity:
Return callPack.cartons.

If user asks about damage:
Return callPack.damageDescription.

If user asks about weight or missing info:
Return
“ I do not have that information. I will check.”

If user asks whether shipment is possible:
Return
“ Please let me know whether shipment will be possible after the inspection.”

This keeps operational accuracy extremely high.

8. ASR, LLM, and TTS Services
ASR Requirements

Streaming transcription

Partial and final segments

Timestamps for silence modeling

Fast turnaround for low latency

LLM Requirements

Constrained prompt structure

No free-form creativity

Ability to generate short, polite phrases

Obey template boundaries

React deterministically based on Call Pack

TTS Requirements

Accept pacing and pause hints

Support Japanese mora timing or English stress timing

Natural prosody at low latency

No mispronunciation of variable values

9. Call Scheduler

Enforces operational rules:

Up to 3 attempts

1 hour between attempts

No voicemail

Detect voicemail through energy patterns

Respect local business hours

Log each attempt with timestamps

10. Logging and Post-Call Output

After each call:

Outputs Provided

Final transcript (single-language)

A structured call summary

Extracted variables used in the conversation

Call status record (success, no answer, voicemail blocked, etc.)

Storage

Retain logs for 90 days

Store in S3 or a database

Use callId and orderId as primary keys

11. Non-Functional Requirements
Latency Target

End-to-end (ASR → LLM → TTS → playback)
200–400 ms maximum.

Reliability

Auto-reconnect for streaming services

Conversation must gracefully continue after intermittent ASR/TTS delay

Observability

Log:

Silence durations

Response timing

Turn-taking behavior

Template usage

Rule-based response triggers

These logs enable continuous tuning of the cultural timing model.
import asyncio
import logging
import os
from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import noise_cancellation, silero, deepgram, openai, cartesia
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger(__name__)
load_dotenv(".env.local")
instructions = """You are a helpful voice AI assistant. 
You eagerly assist users with their questions by providing information from your extensive knowledge.
Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
You are curious, friendly, and have a sense of humor."""

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=instructions,
        )

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    # Determine language from environment or default to English
    # In production, this would come from your Call Pack
    language = os.getenv("AGENT_LANGUAGE", "en-US")
    
    # Configure session timing parameters
    # For Japanese: more conservative interruption handling
    # For English: more tolerant interruption handling
    false_interruption_timeout = 2.5 if language.startswith("ja") else 2.0
    resume_false_interruption = True  # Resume after false interruption
    min_interruption_duration = 0.8 if language.startswith("ja") else 0.3
    min_response_delay = 0.2 if language.startswith("ja") else 0.05
    
    # Configure STT - Use Deepgram plugin with your own API key
    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_api_key:
        logger.error(
            "DEEPGRAM_API_KEY not found in environment. "
            "Please set it in your .env.local file. "
            "Get your API key from https://console.deepgram.com/"
        )
        raise ValueError("DEEPGRAM_API_KEY is required. Please set it in your .env.local file.")
    
    logger.info("Deepgram API key found, using Deepgram plugin")
    try:
        if language.startswith("ja"):
            # Use Nova-2 model for Japanese (supports ja language)
            stt = deepgram.STTv2(
                model="nova-3-general",
            )
            tts_language = "ja"
            logger.info("Using Deepgram nova-3-general model for Japanese")
        else:
            # Use Nova-2 model for English
            stt = deepgram.STTv2(
                model="flux-general-en",
            )
            tts_language = "en"
            logger.info("Using Deepgram flux-general-en model for English")
    except Exception as e:
        logger.error(f"Failed to initialize Deepgram STT: {e}")
        raise
    
    # Configure TTS - Use Cartesia plugin with your own API key
    cartesia_api_key = os.getenv("CARTESIA_API_KEY")
    if not cartesia_api_key:
        logger.error(
            "CARTESIA_API_KEY not found in environment. "
            "Please set it in your .env.local file. "
            "Get your API key from https://play.cartesia.ai/keys"
        )
        raise ValueError("CARTESIA_API_KEY is required. Please set it in your .env.local file.")
    
    logger.info("Cartesia API key found, using Cartesia plugin")
    
    # TTS parameters - can be overridden via environment variables
    tts_speed = float(os.getenv("TTS_SPEED", "1.0"))
    tts_volume = float(os.getenv("TTS_VOLUME", "1.0"))
    tts_emotion = os.getenv("TTS_EMOTION", "calm" if language.startswith("ja") else "friendly")
    
    # TTS configuration - Cartesia with language and voice parameters
    try:
        tts = cartesia.TTS(
            model="sonic-3",
            voice="0834f3df-e650-4766-a20c-5a93a43aa6e3",
            language=tts_language,
            speed=tts_speed,
            volume=tts_volume,
            emotion=tts_emotion,
        )
        logger.info(f"Using Cartesia TTS (model: sonic-3, language: {tts_language})")
    except Exception as e:
        logger.error(f"Failed to initialize Cartesia TTS: {e}")
        raise
    
    # Configure LLM - Use OpenAI plugin with your own API key
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error(
            "OPENAI_API_KEY not found in environment. "
            "Please set it in your .env.local file. "
            "Get your API key from https://platform.openai.com/api-keys"
        )
        raise ValueError("OPENAI_API_KEY is required. Please set it in your .env.local file.")
    
    logger.info("OpenAI API key found, using OpenAI plugin")
    try:
        llm = openai.LLM(
            model="gpt-4o-mini",  # OpenAI model name (not the inference format)
        )
        logger.info("Using OpenAI LLM (model: gpt-4o-mini)")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI LLM: {e}")
        raise
    
    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
        # Apply cultural timing rules
        min_endpointing_delay=min_response_delay,
        allow_interruptions=True,  # Always allow, but control via cultural rules
        min_interruption_duration=min_interruption_duration,
        min_interruption_words=2,  # Require at least one word for interruption
        false_interruption_timeout=false_interruption_timeout,
        resume_false_interruption=resume_false_interruption,
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )


    # Generate initial greeting
    await session.generate_reply(
        instructions="Greet the user and offer your assistance."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
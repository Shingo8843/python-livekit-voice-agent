import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, cli
from livekit.plugins import noise_cancellation, silero, deepgram, openai, cartesia
from livekit.plugins.turn_detector.multilingual import MultilingualModel

try:
    from .model import get_conversational_config
    from .tools import ALL_TOOLS
except ImportError:
    # Fallback for when running as script
    from model import get_conversational_config
    from tools import ALL_TOOLS

logger = logging.getLogger(__name__)
load_dotenv(".env.local")


def load_prompt_variables(language: str) -> dict:
    """
    Load prompt variables from JSON file based on language.
    
    Args:
        language: Language code (e.g., "en-US", "ja-JP")
    
    Returns:
        Dictionary of variables for the language
    """
    # Determine which language key to use
    lang_key = "ja" if language.startswith("ja") else "en"
    
    # Get the directory where this file is located
    current_dir = Path(__file__).parent
    variables_path = current_dir / "prompt_variables.json"
    
    try:
        with open(variables_path, "r", encoding="utf-8") as f:
            variables_data = json.load(f)
        
        # Get variables for the specific language
        variables = variables_data.get(lang_key, {})
        logger.info(f"Loaded prompt variables for language: {lang_key}")
        return variables
    except FileNotFoundError:
        logger.warning(f"Prompt variables file not found at {variables_path}, using empty variables")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON file {variables_path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading prompt variables: {e}")
        return {}


def load_prompt(language: str) -> str:
    """
    Load prompt file based on language and substitute variables.
    
    Args:
        language: Language code (e.g., "en-US", "ja-JP")
    
    Returns:
        Prompt text from the appropriate file with variables substituted
    """
    # Determine which prompt file to load
    if language.startswith("ja"):
        prompt_file = "prompt_ja.txt"
    else:
        prompt_file = "prompt_en.txt"
    
    # Get the directory where this file is located
    current_dir = Path(__file__).parent
    prompt_path = current_dir / prompt_file
    
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()
        logger.info(f"Loaded prompt from {prompt_file}")
        
        # Load variables and substitute them
        variables = load_prompt_variables(language)
        if variables:
            # Replace all {{variable}} placeholders with values from JSON
            for var_name, var_value in variables.items():
                placeholder = f"{{{{{var_name}}}}}"
                prompt_text = prompt_text.replace(placeholder, str(var_value))
            logger.info(f"Substituted {len(variables)} variables in prompt")
        else:
            logger.warning("No variables loaded, prompt will contain placeholders")
        
        return prompt_text
    except FileNotFoundError:
        logger.warning(f"Prompt file {prompt_file} not found at {prompt_path}, using default instructions")
        # Fallback to default instructions
        if language.startswith("ja"):
            return """あなたは日本語を話すアシスタントです。
ユーザーの質問に対して、迅速かつ丁寧に答えます。
回答は簡潔かつ明瞭で、複雑な書式や記号を含まず、絵文字やアスタリスクなどの特殊文字も使用しません。
あなたは好奇心旺盛で友好的で、少し面白いジョークを言うことができます。"""
        else:
            return """You are a helpful voice AI assistant. 
You eagerly assist users with their questions by providing information from your extensive knowledge.
Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
You are curious, friendly, and have a sense of humor."""
    except Exception as e:
        logger.error(f"Error loading prompt file {prompt_file}: {e}")
        raise


class Assistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(
            instructions=instructions,
            tools=ALL_TOOLS,
        )

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    # Determine language from environment or default to English
    # In production, this would come from your Call Pack
    language = os.getenv("AGENT_LANGUAGE", "en-US")
    
    # Load prompt instructions from file based on language
    instructions = load_prompt(language)
    
    # Get conversational design configuration based on language
    conversational_config = get_conversational_config(
        language,
        use_turn_detector=True,
        preemptive_generation=os.getenv("PREEMPTIVE_GENERATION", "false").lower() == "true",
        user_away_timeout=float(os.getenv("USER_AWAY_TIMEOUT", "15.0")) if os.getenv("USER_AWAY_TIMEOUT") else None,
    )
    # TTS parameters - can be overridden via environment variables
    tts_speed = float(os.getenv("TTS_SPEED", "1.0"))
    tts_volume = float(os.getenv("TTS_VOLUME", "1.0"))
    tts_emotion = os.getenv("TTS_EMOTION", "calm" if language.startswith("ja") else "friendly")
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
            # For Japanese: Use nova-3 model (Deepgram's latest model)
            stt = deepgram.STT(
                model="nova-3",
                language="ja",
            )
            tts_language = "ja"
            logger.info("Using Deepgram nova-3 model for Japanese")
        else:
            # Use flux model for English - can use simple model name or 3-part format
            stt = deepgram.STTv2(
                model="flux-general-en",  # 3 parts: flux, general, en
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
            model="gpt-4.1",  # OpenAI model name (not the inference format)
        )
        logger.info("Using OpenAI LLM (model: gpt-4.1)")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI LLM: {e}")
        raise
    
    # Create AgentSession with language-appropriate conversational configuration
    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=silero.VAD.load(),
        **conversational_config.to_dict(),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(instructions=instructions),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

    # Official pattern: Use job context shutdown callback for post-processing and cleanup
    # Shutdown hooks run AFTER session.shutdown() completes
    # The framework waits up to 60 seconds for shutdown hooks to complete
    # Reference: https://docs.livekit.io/agents/server/job/#post-processing-and-cleanup
    async def on_job_shutdown():
        # In console mode, exit the script after cleanup
        # The framework has already shut down the session and cleaned up child processes
        if cli.AgentsConsole.get_instance().enabled:
            logger.info("Job shutdown complete, exiting console mode")
            # Give a brief moment for any final cleanup, then exit
            await asyncio.sleep(0.5)
            sys.exit(0)
    
    ctx.add_shutdown_callback(on_job_shutdown)

    # Generate initial greeting
    await session.generate_reply(
        instructions="Greet the user and offer your assistance."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
"""
Tools for the voice agent.

This module contains function tools that the agent can use during conversations.
Tools are decorated with @function_tool and can be called by the LLM when needed.
"""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from livekit.agents import RunContext, ToolError, function_tool
from pydantic import Field

logger = logging.getLogger(__name__)


@function_tool
async def get_current_time(ctx: RunContext) -> str:
    """
    Get the current date and time.
    
    Use this when the user asks about the current time, date, or what day it is.
    """
    now = datetime.now()
    return f"The current date and time is {now.strftime('%A, %B %d, %Y at %I:%M %p')}"


@function_tool
async def search_knowledge_base(
    ctx: RunContext,
    query: Annotated[
        str,
        Field(description="The search query or question to look up")
    ]
) -> str:
    """
    Search a knowledge base for information.
    
    Use this when the user asks about specific information that might be in a knowledge base,
    such as product details, company information, or documentation.
    
    Args:
        query: The search query or question
    """
    # This is a placeholder implementation
    # In a real application, you would connect to your knowledge base or database here
    logger.info(f"Searching knowledge base for: {query}")
    
    # Example: You could integrate with a vector database, API, or other data source
    # For now, return a placeholder response
    return f"I searched the knowledge base for '{query}', but no specific information was found. Please provide more details or check your knowledge base configuration."


@function_tool
async def hang_up(
    ctx: RunContext,
    goodbye_message: Annotated[
        str | None,
        Field(
            description="Optional custom goodbye message to say before hanging up. "
            "If not provided, a default friendly goodbye will be used."
        )
    ] = None
) -> str:
    """
    End the call and hang up.
    
    Use this when the user wants to end the conversation, says goodbye, or explicitly asks to hang up.
    Always say a brief, friendly goodbye before hanging up.
    
    Args:
        goodbye_message: Optional custom message to say before hanging up. 
                         If not provided, defaults to a friendly goodbye message.
    
    This will gracefully terminate the call session after saying the goodbye message.
    """
    logger.info("Hanging up the call")
    
    # Use provided message or default
    message = goodbye_message or "Thank you for calling. Have a great day! Goodbye!"
    
    # Say goodbye message, then shutdown
    # This ensures the message is spoken before the call ends
    await ctx.session.say(message, allow_interruptions=False)
    
    # Gracefully shutdown the session, draining any pending speech
    ctx.session.shutdown(drain=True)
    
    return "Call ended"


@function_tool
async def wait(ctx: RunContext) -> str:
    """
    Wait for 3 seconds before continuing.
    
    Use this when the user asks the agent to wait, pause, or hold on for a moment.
    This tool will pause the conversation for exactly 3 seconds.
    """
    logger.info("Waiting for 3 seconds")
    await asyncio.sleep(3)
    return "Wait complete. Ready to continue."


@function_tool
async def repeat_last_message(
    ctx: RunContext,
    message: Annotated[
        str | None,
        Field(
            description="The message to repeat. If not provided, the agent should repeat "
            "its last spoken message. Use this when the user asks to repeat, say that again, "
            "or didn't hear what was said."
        )
    ] = None
) -> str:
    """
    Repeat the last message or a specific message to the user.
    
    Use this when the user asks to repeat what was said, says they didn't hear something,
    or asks "what did you say?".
    
    Args:
        message: Optional specific message to repeat. If not provided, repeat the last message.
    """
    logger.info("Repeating last message")
    if message:
        await ctx.session.say(message, allow_interruptions=True)
        return f"Repeated: {message}"
    else:
        # If no message provided, the agent should naturally repeat its last statement
        return "I'll repeat that for you."


@function_tool
async def remember_information(
    ctx: RunContext,
    key: Annotated[
        str,
        Field(description="A short key or label to identify this information (e.g., 'user_name', 'preference', 'appointment_time')")
    ],
    value: Annotated[
        str,
        Field(description="The information to remember for later in the conversation")
    ],
    description: Annotated[
        str | None,
        Field(description="Optional description of what this information represents")
    ] = None
) -> str:
    """
    Store information in the conversation context to remember for later.
    
    Use this when the user provides information that should be remembered throughout
    the conversation, such as their name, preferences, appointment details, or other
    important facts.
    
    Args:
        key: A short identifier for this information
        value: The actual information to store
        description: Optional description of what this information is
    """
    logger.info(f"Remembering information: {key} = {value}")
    
    # Store in session userdata for persistence across the conversation
    if not hasattr(ctx.session.userdata, 'remembered_info'):
        ctx.session.userdata.remembered_info = {}
    
    ctx.session.userdata.remembered_info[key] = {
        'value': value,
        'description': description,
        'timestamp': datetime.now().isoformat()
    }
    
    desc_text = f" ({description})" if description else ""
    return f"I've remembered {key}{desc_text}: {value}"


@function_tool
async def recall_information(
    ctx: RunContext,
    key: Annotated[
        str,
        Field(description="The key or label of the information to recall")
    ]
) -> str:
    """
    Recall previously stored information from the conversation.
    
    Use this when you need to retrieve information that was stored earlier using
    the remember_information tool.
    
    Args:
        key: The key identifying the information to recall
    """
    logger.info(f"Recalling information for key: {key}")
    
    if not hasattr(ctx.session.userdata, 'remembered_info'):
        return f"I don't have any information stored for '{key}'."
    
    remembered = ctx.session.userdata.remembered_info
    if key not in remembered:
        return f"I don't have any information stored for '{key}'."
    
    info = remembered[key]
    desc_text = f" ({info['description']})" if info.get('description') else ""
    return f"I remember {key}{desc_text}: {info['value']}"


@function_tool
async def transfer_to_human(
    ctx: RunContext,
    reason: Annotated[
        str | None,
        Field(
            description="Optional reason for the transfer (e.g., 'complex issue', 'user requested', 'billing inquiry')"
        )
    ] = None,
    transfer_message: Annotated[
        str | None,
        Field(
            description="Optional message to say to the user before transferring. "
            "If not provided, a default message will be used."
        )
    ] = None
) -> str:
    """
    Transfer the conversation to a human agent.
    
    Use this when the user explicitly requests to speak with a human, when the issue
    is too complex for the AI to handle, or when escalation is appropriate.
    
    Args:
        reason: Optional reason for the transfer
        transfer_message: Optional custom message to say before transferring
    """
    logger.info(f"Transferring to human agent. Reason: {reason or 'Not specified'}")
    
    # In a real implementation, you would trigger the transfer logic here
    # This might involve updating session state, calling an API, or triggering a workflow
    
    message = transfer_message or (
        "I'm transferring you to a human agent who can better assist you. "
        "Please hold for just a moment."
    )
    
    await ctx.session.say(message, allow_interruptions=False)
    
    # Note: In a real implementation, you would implement the actual transfer logic here
    # This might involve agent handoff, updating room metadata, or calling external APIs
    
    return f"Transfer initiated. Reason: {reason or 'User requested'}"


@function_tool
async def confirm_understanding(
    ctx: RunContext,
    what_to_confirm: Annotated[
        str,
        Field(description="What the agent understood that needs confirmation from the user")
    ]
) -> str:
    """
    Explicitly confirm understanding of something the user said.
    
    Use this when you want to verify that you understood something correctly,
    especially for important information like dates, names, numbers, or instructions.
    This helps prevent misunderstandings in voice conversations.
    
    Args:
        what_to_confirm: What you understood that needs confirmation
    """
    logger.info(f"Confirming understanding: {what_to_confirm}")
    
    confirmation_message = f"Just to confirm, I understand: {what_to_confirm}. Is that correct?"
    await ctx.session.say(confirmation_message, allow_interruptions=True)
    
    return f"Asked for confirmation: {what_to_confirm}"


# List of all available tools
# Add tools to this list to make them available to the agent
ALL_TOOLS = [
    get_current_time,
    search_knowledge_base,
    hang_up,
    wait,
    repeat_last_message,
    remember_information,
    recall_information,
    transfer_to_human,
    confirm_understanding,
]


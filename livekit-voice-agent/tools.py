"""
Tools for the voice agent.

This module contains function tools that the agent can use during conversations.
Tools are decorated with @function_tool and can be called by the LLM when needed.
"""

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


# List of all available tools
# Add tools to this list to make them available to the agent
ALL_TOOLS = [
    get_current_time,
    search_knowledge_base,
    hang_up,
]


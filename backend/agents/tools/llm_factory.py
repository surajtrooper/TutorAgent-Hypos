"""
agents/tools/llm_factory.py
───────────────────────────
Returns a ChatGroq model instance wired to the same API key and model as
the rest of the app, ready to be passed to create_react_agent().

Using ChatGroq instead of the raw groq SDK because LangGraph's
create_react_agent() requires a LangChain chat model that supports
.bind_tools() — the native Groq client does not expose this interface.
"""

from functools import lru_cache
from langchain_groq import ChatGroq
from core.config import settings


@lru_cache(maxsize=1)
def get_agent_llm() -> ChatGroq:
    """
    Cached ChatGroq model for use inside tool-calling agents.
    llama-3.3-70b-versatile supports native function/tool calling on Groq.
    """
    model_name = settings.LLM_MODEL
    # ChatGroq does not want the 'groq/' prefix that LiteLLM uses
    model_name = model_name.replace("groq/", "")

    return ChatGroq(
        model=model_name,
        api_key=settings.GROQ_API_KEY,
        temperature=0,          # deterministic output for JSON generation
        max_retries=3,
    )

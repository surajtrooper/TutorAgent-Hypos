"""
agents/roadmap_agent.py
───────────────────────
TRUE ReAct Agent — Roadmap Generation.

Architecture change from previous version:
  BEFORE: Fixed LangGraph pipeline (fetch_profile → recall_memory →
          generate_roadmap → save_to_mongo → save_to_cognee).
          LLM only called once, hardcoded sequence, zero LLM agency.

  NOW:    LangGraph create_react_agent() with 4 registered tools.
          The LLM decides which tools to call and when:
            1. fetch_student_profile    → understand who the student is
            2. recall_student_context   → remember prior history from Cognee
            3. (generates roadmap internally using its reasoning)
            4. save_roadmap_to_db       → persist to MongoDB
            5. save_roadmap_to_memory   → write to Cognee knowledge graph

Tools registered:
  fetch_student_profile  → MongoDB: pull student document with goal weights
  recall_student_context → Cognee: multi-hop graph recall + ontology context
  save_roadmap_to_db     → MongoDB: upsert the 12-week plan
  save_roadmap_to_memory → Cognee: store roadmap as typed graph entities

Entrypoint:
  result = await run_roadmap_agent(student_id)
  # returns { "weeks": [...] }
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from agents.tools.llm_factory import get_agent_llm
from agents.tools.roadmap_tools import (
    fetch_student_profile,
    recall_student_context,
    save_roadmap_to_db,
    save_roadmap_to_memory,
)

logger = logging.getLogger(__name__)


# ── System prompt ─────────────────────────────────────────────────────────────

ROADMAP_AGENT_SYSTEM = """\
You are an expert academic advisor and AI agent for TrackMind, a personalised
learning platform for college students.

Your job is to create a personalised 12-week learning roadmap for a student.

You have access to these tools — USE THEM IN THIS ORDER:

1. fetch_student_profile(student_id)
   → Retrieve the student's name, year, goal, target role, skills, and goal weights.
   → You MUST call this first.

2. recall_student_context(student_id)
   → Query the student's Cognee knowledge graph for prior history:
     mastered topics, weak areas, previous roadmap, quiz performance.
   → Also retrieves CS topic prerequisite relationships from the shared ontology.
   → Use this context to SKIP basics the student already knows and to ensure
     prerequisite topics appear before advanced ones.

3. Generate the 12-week roadmap yourself (no tool needed):
   → Use the student's goal and the goal_info.distribution from their profile.
   → Respect topic prerequisites from the ontology context.
   → If the student already knows some topics (current_skills), skip basics.
   → Each week must have: "week" (1-12), "focus" (area), "topics" (3-5 concrete topics).
   → Return the roadmap as a JSON object with key "weeks".

4. save_roadmap_to_db(student_id, roadmap_json)
   → Persist the roadmap. Pass the full JSON string {"weeks": [...]} as roadmap_json.

5. save_roadmap_to_memory(student_id, roadmap_summary)
   → Build a compact text summary like:
     "Week 1 [DSA]: Arrays & Two Pointers, Binary Search | Week 2 [DSA]: Recursion..."
   → Pass this to save_roadmap_to_memory so Cognee builds graph edges.

After saving, output ONLY the final roadmap JSON. Do not add any explanation.

JSON format:
{
  "weeks": [
    {
      "week": 1,
      "focus": "DSA",
      "topics": ["Arrays & Two Pointers", "Binary Search", "Sliding Window", "Prefix Sums"]
    },
    ... 12 weeks total ...
  ]
}

Rules:
- Exactly 12 weeks.
- Topics must be concrete and actionable (e.g. "Arrays & Sliding Window", not just "Arrays").
- Progressively increase difficulty week over week.
- Align strongly with the student's goal distribution from their profile.
- If the student already knows some topics, start at intermediate level.
"""


# ── Agent construction ────────────────────────────────────────────────────────

def _build_roadmap_agent():
    """Build and cache the ReAct agent with all roadmap tools registered."""
    llm   = get_agent_llm()
    tools = [fetch_student_profile, recall_student_context, save_roadmap_to_db, save_roadmap_to_memory]

    agent = create_react_agent(llm, tools)
    logger.info(
        "[roadmap_agent] ReAct agent built with %d tools: %s",
        len(tools), [t.name for t in tools]
    )
    return agent


_agent = _build_roadmap_agent()


# ── Output parser ─────────────────────────────────────────────────────────────

def _extract_roadmap_json(content: str) -> dict:
    """
    Extract the roadmap JSON from the agent's final message.
    Handles markdown fences and trailing text.
    """
    content = re.sub(r"```(?:json)?\s*", "", content).strip().rstrip("`").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not extract valid JSON from agent response: {content[:300]}")


# ── Public entrypoint ─────────────────────────────────────────────────────────

async def run_roadmap_agent(student_id: str) -> dict:
    """
    Run the true ReAct roadmap generation agent.

    The LLM will:
      - Call fetch_student_profile to understand the student's goal and skills
      - Call recall_student_context to query Cognee memory + CS ontology graph
      - Generate a 12-week roadmap with proper topic ordering and difficulty curve
      - Call save_roadmap_to_db to persist in MongoDB
      - Call save_roadmap_to_memory to write typed entities into Cognee graph

    Returns:
        dict with key "weeks" — list of 12 week objects

    Raises:
        ValueError: if the agent fails to produce a valid roadmap
    """
    logger.info("[roadmap_agent] Starting ReAct agent | student=%s", student_id)

    user_message = (
        f"Generate a personalised 12-week learning roadmap for student ID: {student_id}\n\n"
        f"Follow your tool usage instructions exactly. "
        f"Make sure to use all 4 tools before returning the final roadmap."
    )

    try:
        result = await _agent.ainvoke({
            "messages": [
                SystemMessage(content=ROADMAP_AGENT_SYSTEM),
                HumanMessage(content=user_message),
            ]
        })

        messages = result.get("messages", [])
        if not messages:
            raise ValueError("Agent returned no messages.")

        final_message = messages[-1]
        content = (
            final_message.content
            if isinstance(final_message.content, str)
            else str(final_message.content)
        )

        logger.info("[roadmap_agent] Agent completed | messages=%d", len(messages))

        # Log the tool call trace
        tool_calls_made = [
            m.tool_calls[0]["name"]
            for m in messages
            if hasattr(m, "tool_calls") and m.tool_calls
        ]
        logger.info("[roadmap_agent] Tool call trace: %s", " → ".join(tool_calls_made))

        # Extract and validate the roadmap JSON
        roadmap = _extract_roadmap_json(content)

        if "weeks" not in roadmap or not isinstance(roadmap["weeks"], list):
            raise ValueError(f"Agent output missing 'weeks'. Got: {list(roadmap.keys())}")

        if len(roadmap["weeks"]) != 12:
            logger.warning(
                "[roadmap_agent] Expected 12 weeks, got %d. Normalising.", len(roadmap["weeks"])
            )

        # Normalise week numbers
        for i, week in enumerate(roadmap["weeks"], start=1):
            week["week"] = i

        logger.info("[roadmap_agent] Roadmap generated successfully | weeks=%d", len(roadmap["weeks"]))
        return roadmap

    except Exception as exc:
        logger.error("[roadmap_agent] ReAct agent failed: %s", exc)
        raise ValueError(f"Roadmap agent failed: {exc}") from exc

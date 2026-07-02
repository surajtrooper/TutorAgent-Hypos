"""
agents/tools/task_tools.py
──────────────────────────
Tool definitions for the Task Agent.

Each function decorated with @tool becomes a callable that the LLM can
choose to invoke at any point in its ReAct loop.  The LLM sees the
function name + docstring as the tool description, and the typed
parameters as its input schema.

Tools available to the Task Agent:
  fetch_today_topic        → determine which roadmap topic is scheduled today
  check_weak_topics        → query Cognee for recent struggles (may override topic)
  get_topic_prerequisites  → query CS ontology for prereq/related topics
  save_daily_task          → persist the generated task to MongoDB
"""

import json
import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ── Tool 1: fetch_today_topic ─────────────────────────────────────────────────

@tool
async def fetch_today_topic(student_id: str) -> str:
    """
    Fetch the student's 12-week roadmap from the database and determine
    which topic is scheduled for today based on how many days have passed
    since the roadmap was generated.

    Returns a JSON string: {"topic": "...", "week": N, "focus": "..."}
    If no roadmap exists, returns {"topic": "CS Fundamentals", "week": 1, "focus": "General"}.
    """
    from db.mongo import get_db

    db = get_db()
    today = datetime.now(timezone.utc)

    try:
        roadmap = await db.roadmaps.find_one({"student_id": student_id})
        if not roadmap:
            logger.warning("[task_tools] No roadmap for student=%s, using fallback topic", student_id)
            return json.dumps({"topic": "CS Fundamentals", "week": 1, "focus": "General"})

        gen_at = roadmap.get("generated_at", today)
        if gen_at.tzinfo is None:
            gen_at = gen_at.replace(tzinfo=timezone.utc)

        days_diff = (today - gen_at).days
        week_num  = max(1, min(12, (days_diff // 7) + 1))

        weeks     = roadmap.get("weeks", [])
        week_plan = next((w for w in weeks if w.get("week") == week_num), weeks[0] if weeks else None)

        if not week_plan:
            return json.dumps({"topic": "CS Fundamentals", "week": week_num, "focus": "General"})

        topics       = week_plan.get("topics", ["CS Fundamentals"])
        topic_index  = days_diff % len(topics)
        selected     = topics[topic_index]

        logger.info("[task_tools] fetch_today_topic | week=%d topic='%s'", week_num, selected)
        return json.dumps({
            "topic": selected,
            "week":  week_num,
            "focus": week_plan.get("focus", "General"),
        })

    except Exception as exc:
        logger.error("[task_tools] fetch_today_topic error: %s", exc)
        return json.dumps({"error": str(exc), "topic": "CS Fundamentals", "week": 1, "focus": "General"})


# ── Tool 2: check_weak_topics ─────────────────────────────────────────────────

@tool
async def check_weak_topics(student_id: str) -> str:
    """
    Query the student's Cognee memory graph to find any topics they have
    recently struggled with that need revision.

    Returns a JSON string: {"weak_topic": "Dynamic Programming"} if a
    weak area is found, or {"weak_topic": null} if the student is on track.

    The Task Agent should call this AFTER fetch_today_topic.  If a weak
    topic is found, it should override today's scheduled topic with a
    revision session on the weak topic.
    """
    from services.cognee_service import recall
    from services.llm_service import chat_json

    try:
        memory_result = await recall(student_id, "what has student struggled with recently, weak topics")
        if not memory_result:
            return json.dumps({"weak_topic": None})

        # Ask the LLM to parse which specific topic to revise
        parsed = await chat_json([
            {
                "role": "system",
                "content": (
                    "You are a parser. Analyze the memory query results and determine if there is a "
                    "specific technical topic the student has struggled with recently that needs revision. "
                    "Return ONLY valid JSON. No markdown, no explanation."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Memory results:\n{memory_result}\n\n"
                    "If a clear weak topic is found, return {\"weak_topic\": \"<topic_name>\"}. "
                    "If no clear weak topic, return {\"weak_topic\": null}."
                )
            }
        ])

        weak_topic = parsed.get("weak_topic")
        logger.info("[task_tools] check_weak_topics | student=%s | weak_topic=%s", student_id, weak_topic)
        return json.dumps({"weak_topic": weak_topic})

    except Exception as exc:
        logger.error("[task_tools] check_weak_topics error: %s", exc)
        return json.dumps({"weak_topic": None})


# ── Tool 3: get_topic_prerequisites ──────────────────────────────────────────

@tool
async def get_topic_prerequisites(topic: str) -> str:
    """
    Query the shared CS topic knowledge graph (Cognee ontology dataset) to
    find prerequisite and related topics for the given topic.

    Returns a plain-text description of topic relationships, e.g.:
    "Arrays is a prerequisite for Sliding Window. Sliding Window depends on Arrays."

    The Task Agent should call this to enrich the quiz with 1-2 bridging
    questions that test prerequisite knowledge alongside today's main topic.
    Returns an empty string if no relationships are found.
    """
    from services.cognee_service import recall_topic_prerequisites

    try:
        result = await recall_topic_prerequisites(topic)
        logger.info("[task_tools] get_topic_prerequisites | topic='%s' | found=%s", topic, bool(result))
        return result or f"No prerequisite relationships found for '{topic}' in the knowledge graph."
    except Exception as exc:
        logger.error("[task_tools] get_topic_prerequisites error: %s", exc)
        return f"Could not retrieve prerequisites for '{topic}'."


# ── Tool 4: save_daily_task ───────────────────────────────────────────────────

@tool
async def save_daily_task(student_id: str, date: str, topic: str, task_json: str) -> str:
    """
    Persist the generated daily task (resource + 5 MCQs) to MongoDB.

    Parameters:
        student_id : The student's MongoDB ObjectId string.
        date       : Today's date in YYYY-MM-DD format.
        topic      : The topic for today's session.
        task_json  : A JSON string containing the task with keys:
                     "resource" (title + content) and "questions" (list of 5 MCQs).

    Returns a JSON string: {"task_id": "<mongo_id>", "status": "saved"}
    or {"status": "error", "detail": "..."} on failure.
    """
    from db.mongo import get_db

    db = get_db()

    try:
        task_data = json.loads(task_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"status": "error", "detail": f"Invalid task_json: {exc}"})

    doc = {
        "student_id": student_id,
        "date":       date,
        "topic":      topic,
        "resource":   task_data.get("resource", {}),
        "questions":  task_data.get("questions", []),
        "submitted":  False,
        "score":      None,
        "struggled":  False,
    }

    try:
        result = await db.daily_tasks.update_one(
            {"student_id": student_id, "date": date},
            {"$set": doc},
            upsert=True,
        )
        if result.upserted_id:
            task_id = str(result.upserted_id)
        else:
            existing = await db.daily_tasks.find_one({"student_id": student_id, "date": date})
            task_id  = str(existing["_id"]) if existing else "unknown"

        logger.info("[task_tools] save_daily_task OK | student=%s | task_id=%s", student_id, task_id)
        return json.dumps({"task_id": task_id, "status": "saved"})

    except Exception as exc:
        logger.error("[task_tools] save_daily_task error: %s", exc)
        return json.dumps({"status": "error", "detail": str(exc)})

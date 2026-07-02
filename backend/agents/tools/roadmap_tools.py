"""
agents/tools/roadmap_tools.py
─────────────────────────────
Tool definitions for the Roadmap Agent.

Tools available:
  fetch_student_profile    → pull student document from MongoDB
  recall_student_context   → query Cognee graph for prior student history
  save_roadmap_to_db       → upsert the generated roadmap in MongoDB
  save_roadmap_to_memory   → store roadmap summary in Cognee knowledge graph
"""

import json
import logging
from datetime import datetime, timezone

from bson import ObjectId
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# Goal → topic weight mapping (same as before, needed for system prompt construction)
GOAL_WEIGHTS: dict[str, dict] = {
    "FAANG": {
        "description": "targeting FAANG / top-tier tech companies",
        "distribution": "60% DSA & Algorithms, 20% System Design, 20% Projects & CS Fundamentals",
        "focus_areas": ["DSA", "System Design", "Projects", "CS Fundamentals"],
    },
    "Startup": {
        "description": "targeting early-stage startup roles",
        "distribution": "40% Web/App Development, 30% DSA, 30% Projects & Product Thinking",
        "focus_areas": ["Web/App Development", "DSA", "Projects", "Product Thinking"],
    },
    "MS Abroad": {
        "description": "targeting Masters programs abroad",
        "distribution": "40% DSA, 30% Research/ML Fundamentals, 30% Projects & Publications",
        "focus_areas": ["DSA", "Machine Learning", "Research Projects", "Math Foundations"],
    },
    "Govt": {
        "description": "targeting government / PSU competitive exams",
        "distribution": "60% Aptitude & Reasoning, 20% CS Fundamentals, 20% DSA",
        "focus_areas": ["Aptitude", "Reasoning", "CS Fundamentals", "DSA"],
    },
    "Freelance": {
        "description": "targeting freelance / independent development work",
        "distribution": "50% Web/App Development, 30% Projects & Portfolio, 20% DSA",
        "focus_areas": ["Web Development", "App Development", "Portfolio Projects", "DSA"],
    },
}


# ── Tool 1: fetch_student_profile ─────────────────────────────────────────────

@tool
async def fetch_student_profile(student_id: str) -> str:
    """
    Fetch the student's full profile from MongoDB, including their name,
    year, goal, target role, and current skills.

    Returns a JSON string of the student document, or an error object.
    The Roadmap Agent must call this first to understand who the student is
    before generating a personalised roadmap.
    """
    from db.mongo import get_db

    db = get_db()
    try:
        student = await db.students.find_one({"_id": ObjectId(student_id)})
        if not student:
            return json.dumps({"error": f"Student {student_id} not found."})

        student["_id"] = str(student["_id"])
        # Remove sensitive fields
        student.pop("hashed_password", None)

        goal     = student.get("goal", "FAANG")
        goal_info = GOAL_WEIGHTS.get(goal, GOAL_WEIGHTS["FAANG"])
        student["goal_info"] = goal_info   # attach goal weights so agent has full context

        logger.info("[roadmap_tools] fetch_student_profile OK | student=%s | goal=%s", student_id, goal)
        return json.dumps(student, default=str)

    except Exception as exc:
        logger.error("[roadmap_tools] fetch_student_profile error: %s", exc)
        return json.dumps({"error": str(exc)})


# ── Tool 2: recall_student_context ────────────────────────────────────────────

@tool
async def recall_student_context(student_id: str) -> str:
    """
    Query the student's Cognee knowledge graph to retrieve any prior context:
    previous roadmaps, mastered topics, weak areas, quiz history, interview
    scores, and the CS topic prerequisite ontology (for correct topic ordering).

    Returns a plain-text summary of everything Cognee knows about the student.
    Returns an empty string if no memory exists yet (first-time user).

    The Roadmap Agent should call this AFTER fetching the student profile to
    enrich roadmap generation with memory-aware context.
    """
    from services.cognee_service import recall

    try:
        context = await recall(
            student_id,
            "student profile, skills, goals, previous roadmap, mastered topics, weak areas, quiz performance",
            include_ontology=True,
        )
        logger.info(
            "[roadmap_tools] recall_student_context | student=%s | has_context=%s",
            student_id, bool(context)
        )
        return context or "No prior memory found for this student. This appears to be a fresh start."

    except Exception as exc:
        logger.error("[roadmap_tools] recall_student_context error: %s", exc)
        return "Memory recall failed. Proceed without historical context."


# ── Tool 3: save_roadmap_to_db ────────────────────────────────────────────────

@tool
async def save_roadmap_to_db(student_id: str, roadmap_json: str) -> str:
    """
    Upsert the generated 12-week roadmap into the MongoDB roadmaps collection.

    Parameters:
        student_id   : The student's MongoDB ObjectId string.
        roadmap_json : A JSON string with key "weeks" — a list of 12 objects,
                       each with "week" (int), "focus" (str), "topics" (list[str]).

    Returns: {"status": "saved"} on success, or {"status": "error", "detail": "..."}.

    The Roadmap Agent should call this immediately after generating the roadmap
    so results are persisted before writing to Cognee.
    """
    from db.mongo import get_db

    db = get_db()
    try:
        roadmap = json.loads(roadmap_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"status": "error", "detail": f"Invalid roadmap_json: {exc}"})

    weeks = roadmap.get("weeks", [])
    if not weeks:
        return json.dumps({"status": "error", "detail": "Roadmap has no weeks."})

    # Normalise week numbers
    for i, week in enumerate(weeks, start=1):
        week["week"] = i

    doc = {
        "student_id":   student_id,
        "weeks":        weeks,
        "generated_at": datetime.now(timezone.utc),
    }

    try:
        await db.roadmaps.update_one(
            {"student_id": student_id},
            {"$set": doc},
            upsert=True,
        )
        logger.info("[roadmap_tools] save_roadmap_to_db OK | student=%s | weeks=%d", student_id, len(weeks))
        return json.dumps({"status": "saved", "weeks_count": len(weeks)})

    except Exception as exc:
        logger.error("[roadmap_tools] save_roadmap_to_db error: %s", exc)
        return json.dumps({"status": "error", "detail": str(exc)})


# ── Tool 4: save_roadmap_to_memory ───────────────────────────────────────────

@tool
async def save_roadmap_to_memory(student_id: str, roadmap_summary: str) -> str:
    """
    Store a compact text summary of the generated 12-week roadmap in the
    student's Cognee knowledge graph.

    Parameters:
        student_id      : The student's MongoDB ObjectId string.
        roadmap_summary : A short plain-text summary of the roadmap, e.g.:
                          "Week 1 [DSA]: Arrays, Two Pointers | Week 2 [DSA]: Recursion..."

    This call triggers cognee.add() + cognee.cognify() which extracts graph
    entities from the summary and builds typed edges between the student node
    and each weekly topic node.

    Returns: {"status": "memorised"} on success, {"status": "error"} on failure.
    """
    from services.cognee_service import remember_roadmap

    try:
        await remember_roadmap(student_id, roadmap_summary)
        logger.info("[roadmap_tools] save_roadmap_to_memory OK | student=%s", student_id)
        return json.dumps({"status": "memorised"})
    except Exception as exc:
        logger.error("[roadmap_tools] save_roadmap_to_memory error: %s", exc)
        return json.dumps({"status": "error", "detail": str(exc)})

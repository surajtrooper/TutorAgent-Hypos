
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure
from core.config import settings
import logging

logger = logging.getLogger(__name__)

client: AsyncIOMotorClient | None = None
db = None  # type: ignore[assignment]  # typed via motor internals


async def connect_to_mongo() -> None:
    """
    Open the Motor connection and verify it with a server ping.
    Called from main.py lifespan on startup.
    """
    global client, db

    logger.info("Connecting to MongoDB…")
    client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        serverSelectionTimeoutMS=5_000,   # fail fast during startup
        uuidRepresentation="standard",
    )

    # Confirm the server is reachable before we accept traffic
    await client.admin.command("ping")
    logger.info("MongoDB connection established ✓")

    db = client[settings.DB_NAME]
    await _ensure_indexes()


async def close_mongo_connection() -> None:
    """
    Gracefully close the Motor connection.
    Called from main.py lifespan on shutdown.
    """
    global client
    if client is not None:
        client.close()
        logger.info("MongoDB connection closed ✓")


async def _ensure_indexes() -> None:
    """
    Create indexes that are critical for query performance.
    Motor's create_index is idempotent — safe to run on every startup.
    """
    # students — email must be unique
    await db.students.create_index(
        [("email", ASCENDING)], unique=True, name="students_email_unique"
    )

    # roadmaps — one roadmap per student (enforced at app layer too)
    await db.roadmaps.create_index(
        [("student_id", ASCENDING)], name="roadmaps_student_id"
    )

    # daily_tasks — quick lookup by student + date
    await db.daily_tasks.create_index(
        [("student_id", ASCENDING), ("date", ASCENDING)],
        name="daily_tasks_student_date",
    )

    # interviews — ordered history per student
    await db.interviews.create_index(
        [("student_id", ASCENDING), ("conducted_at", DESCENDING)],
        name="interviews_student_date",
    )

    # progress — one record per (student, topic)
    await db.progress.create_index(
        [("student_id", ASCENDING), ("topic", ASCENDING)],
        unique=True,
        name="progress_student_topic_unique",
    )

    # interview_sessions — temporary store, expire after 24 h via TTL index
    await db.interview_sessions.create_index(
        [("created_at", ASCENDING)],
        expireAfterSeconds=86_400,      # 24 hours
        name="interview_sessions_ttl",
    )

    logger.info("MongoDB indexes verified ✓")


def get_db():
    return db

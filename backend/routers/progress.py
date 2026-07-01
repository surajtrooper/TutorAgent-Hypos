"""
routers/progress.py — stub (Step 7)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/progress", tags=["Progress"])


@router.get("/{student_id}")
async def get_progress(student_id: str):
    return {"message": f"progress stub for {student_id} — coming in Step 7"}

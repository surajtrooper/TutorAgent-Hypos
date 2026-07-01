"""
routers/tasks.py — stub (Step 5)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/tasks", tags=["Daily Tasks"])


@router.get("/today/{student_id}")
async def get_today_task(student_id: str):
    return {"message": f"today's task stub for {student_id} — coming in Step 5"}


@router.post("/submit")
async def submit_task():
    return {"message": "submit task stub — coming in Step 5"}

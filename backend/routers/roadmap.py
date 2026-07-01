"""
routers/roadmap.py — stub (Step 4)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/roadmap", tags=["Roadmap"])


@router.post("/generate")
async def generate_roadmap():
    return {"message": "generate roadmap stub — coming in Step 4"}


@router.get("/{student_id}")
async def get_roadmap(student_id: str):
    return {"message": f"fetch roadmap stub for {student_id} — coming in Step 4"}

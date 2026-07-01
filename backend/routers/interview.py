"""
routers/interview.py — stub (Step 6)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/interview", tags=["Interview"])


@router.post("/start")
async def start_interview():
    return {"message": "start interview stub — coming in Step 6"}


@router.post("/respond")
async def respond_interview():
    return {"message": "respond interview stub — coming in Step 6"}


@router.post("/end")
async def end_interview():
    return {"message": "end interview stub — coming in Step 6"}

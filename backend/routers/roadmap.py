
"""Roadmap API endpoints for Stratify.AI."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routers.auth import get_current_user
from services.roadmap_engine import generate_roadmap

router = APIRouter(prefix="/roadmap", tags=["Roadmap"])
logger = logging.getLogger(__name__)


class RoadmapStepInput(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    outcome: str = Field(min_length=1, max_length=500)
    duration_days: int = Field(default=7, ge=1, le=365)
    dependencies: list[str] = Field(default_factory=list)
    priority: str = "normal"


class RoadmapRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    steps: list[RoadmapStepInput] = Field(min_length=1, max_length=50)
    start_date: str | None = None
    constraints: list[str] = Field(default_factory=list)


@router.post("/generate")
def create_roadmap(
    payload: RoadmapRequest,
    user=Depends(get_current_user),
):
    try:
        roadmap = generate_roadmap(
            goal=payload.goal,
            steps=[step.model_dump(exclude_none=True) for step in payload.steps],
            start_date=payload.start_date,
            constraints=payload.constraints,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Roadmap generation failed for user %s", user["id"])
        raise HTTPException(
            status_code=500,
            detail="Unable to generate roadmap.",
        ) from exc

    return {
        "user_id": user["id"],
        "roadmap": roadmap,
    }

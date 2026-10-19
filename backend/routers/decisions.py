
"""Decision comparison API for Stratify.AI."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routers.auth import get_current_user
from services.decision_engine import compare_options

router = APIRouter(prefix="/decisions", tags=["Decisions"])


class DecisionRequest(BaseModel):
    options: list[dict] = Field(min_length=1, max_length=50)
    criteria: list[dict] = Field(min_length=1, max_length=30)
    constraints: list[dict] = Field(default_factory=list)


@router.post("/compare")
def compare_decision_options(
    payload: DecisionRequest,
    user=Depends(get_current_user),
):
    try:
        result = compare_options(
            options=payload.options,
            criteria=payload.criteria,
            constraints=payload.constraints,
        )
        return {"result": result}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

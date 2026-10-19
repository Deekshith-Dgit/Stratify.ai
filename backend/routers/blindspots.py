
"""Blind-spot analysis API for Stratify.AI."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routers.auth import get_current_user
from services.blindspot_engine import detect_blind_spots

router = APIRouter(prefix="/blindspots", tags=["Blind Spots"])
logger = logging.getLogger(__name__)


class BlindSpotRequest(BaseModel):
    profile: dict = Field(default_factory=dict)


@router.post("/analyze")
def analyze_blind_spots(
    payload: BlindSpotRequest,
    user=Depends(get_current_user),
):
    try:
        result = detect_blind_spots(payload.profile)
        return {"result": result}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Blind-spot analysis failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to analyze the supplied profile.",
        ) from exc

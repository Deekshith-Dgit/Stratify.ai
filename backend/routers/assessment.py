from fastapi import APIRouter, HTTPException
import json
from pathlib import Path

router = APIRouter()

DATA_PATH = Path(__file__).parent.parent / "data" / "assessment_questions.json"

with open(DATA_PATH, "r", encoding="utf-8") as file:
    QUESTIONS = json.load(file)


@router.get("/assessment/start")
def start_assessment():
    return QUESTIONS["start"]


@router.get("/assessment/question/{question_id}")
def get_question(question_id: str):
    if question_id not in QUESTIONS:
        raise HTTPException(status_code=404, detail="Question not found")

    return QUESTIONS[question_id]


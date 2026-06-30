from fastapi import APIRouter 

router = APIRouter()

@router.get("/assessment/start")
def start_assessment():
    return {"question": "who are you?",
            "options":[
                "student",
                "working professional",
                "other"
            ]}


from fastapi import FastAPI
from backend.routers.assessment import router as assessment_router

app = FastAPI()

app.include_router(assessment_router)

@app.get("/")
def home():
    return {"message": "Welcome to Stratify AI"}


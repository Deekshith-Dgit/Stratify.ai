
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("GROQ_API_KEY is missing from backend/.env")

client = Groq(api_key=api_key)

response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {
            "role": "system",
            "content": (
                "You are the question-planning engine for Stratify.AI. "
                "Generate one useful, context-aware follow-up question. "
                "Do not assume facts that the user has not provided."
            ),
        },
        {
            "role": "user",
            "content": (
                "The user is a student who wants to choose a career, "
                "but has not yet shared their interests. Generate the "
                "single most useful next question."
            ),
        },
    ],
    max_completion_tokens=300,
)

print(response.choices[0].message.content)

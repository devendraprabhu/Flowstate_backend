from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import os
from dotenv import load_dotenv
from api.prompts import CONTENT_PROMPT
import requests


load_dotenv()

app = FastAPI()

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "FlowState is alive 🚀"}


class VideoGeneration(BaseModel):
    video_url: str


@app.post("/api/transcribe")
async def transcribe_video(req: VideoGeneration):

    print("Downloading Video...")
    print(req.video_url)

    response = requests.get(req.video_url)

    with open("temp_video.mp4", "wb") as f:
        f.write(response.content)

    print("Video downloaded successfully")

    audio_file = open("temp_video.mp4", "rb")

    transcription_response = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=audio_file,
        language="en"
    )

    transcript = transcription_response.text

    print("Transcript:")
    print(transcript)

    content_response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": CONTENT_PROMPT
            },
            {
                "role": "user",
                "content": transcript
            }
        ],
        model="llama-3.3-70b-versatile"
    )
    import json

    generated_content = content_response.choices[0].message.content
    generated_content = generated_content.replace("```json", "")
    generated_content= generated_content.replace("```json", "")
    generated_content = generated_content.replace("```", "")
    generated_content = generated_content.strip()

    parsed_content = json.loads(generated_content)

    print("Generated Content:")
    print(generated_content)

    return {
        "transcript": transcript,
        "content": parsed_content
    }
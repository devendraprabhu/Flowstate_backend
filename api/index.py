from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import os
from dotenv import load_dotenv
from api.prompts import CONTENT_PROMPT
import requests
from moviepy import VideoFileClip
import base64
import io
from PIL import Image
import uuid
import json
import razorpay
from supabase import create_client, Client

load_dotenv()

app = FastAPI()

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)
razorpay_client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

@app.get("/")
async def root():
    return {"message": "FlowState is alive 🚀"}

class VideoGeneration(BaseModel):
    video_url: str

@app.post("/api/transcribe")
async def transcribe_video(req: VideoGeneration):
    print("Downloading Video...")
    print(req.video_url)
    
    # 1. Generate unique filenames for this specific run
    run_id = str(uuid.uuid4())
    vid_filename = f"{run_id}_video.mp4"
    aud_filename = f"{run_id}_audio.mp3"
    
    try:
        # Download using the unique filename
        response = requests.get(req.video_url)
        with open(vid_filename, "wb") as f:
            f.write(response.content)

        print("Video downloaded successfully")
        
        # Extract audio using the unique filenames
        video_clip = VideoFileClip(vid_filename)
        video_clip.audio.write_audiofile(aud_filename, logger=None)
        
        duration = video_clip.duration
        timestamps = [duration * 0.20, duration * 0.50, duration * 0.80]
        
        base64_frames = []
        for t in timestamps:
            frame = video_clip.get_frame(t)
            img = Image.fromarray(frame)
            img.thumbnail((512, 512))
            buffered = io.BytesIO()
            img.save(buffered, format="WEBP")
            b64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_frames.append(b64_str)

        video_clip.close()

        # Open the unique audio file
        audio_file = open(aud_filename, "rb")

        transcription_response = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=audio_file,
            language="en"
        )
        audio_file.close()
        
        transcript = transcription_response.text
        print("Transcript:")
        print(transcript)
        
        content_response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "system",
                    "content": CONTENT_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Here is the audio transcript (if any): {transcript}\n\nLook at these 3 frames from the video. Based on what you SEE and HEAR, generate the content."},
                        {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{base64_frames[0]}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{base64_frames[1]}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{base64_frames[2]}"}}
                    ]
                }
            ],
        )
        
        generated_content = content_response.choices[0].message.content
        generated_content = generated_content.replace("```json", "").replace("```", "").strip()

        parsed_content = json.loads(generated_content)

        print("Generated Content:")
        print(generated_content)
        
        return {
            "transcript": transcript,
            "content": parsed_content
        }

    except Exception as e:
        print(f"Error processing video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # 2. EMERGENCY CLEANUP: This runs no matter what. 
        # Even if the code crashes above, it will delete the old files.
        if os.path.exists(vid_filename): os.remove(vid_filename)
        if os.path.exists(aud_filename): os.remove(aud_filename)

class OrderRequest(BaseModel):
    amount:int
    user_id:str

@app.post("/api/pricing")
async def pricing(data: OrderRequest):
    amount_in_paise=data.amount * 100
    user= data.user_id

    order_data= {
        "amount":amount_in_paise,
        "currency":"INR",
        "receipt":user
    }
    razorpay_order= razorpay_client.order.create(data=order_data)

    return{
        "id":razorpay_order["id"],
        "amount":razorpay_order["amount"]
    }
class verification(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    user_id: str
    credits_to_add: int

@app.post("/api/verify")
async def verify(data:verification):
    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id':data.razorpay_order_id,
            'razorpay_payment_id':data.razorpay_payment_id,
            'razorpay_signature':data.razorpay_signature
        
        })
        user_response=supabase.table("profiles").select("credits").eq("id",data.user_id).execute()
        current_credits=user_response.data[0]["credits"]
        new_credits=current_credits+data.credits_to_add
        supabase.table("profiles").update({"credits":new_credits}).eq("id",data.user_id).execute()
        return {"status":"success"}
    except Exception as e:
        print(f"🚨 URGENT ERROR DETAILS: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid Payment Signature")

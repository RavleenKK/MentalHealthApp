import os
import uuid
import logging
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, File, UploadFile, HTTPException, Body, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
from dotenv import load_dotenv

# --- Load env ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # optional now

# Choose transcription backend: "local" (faster-whisper) or "openai"
# If not set, default to "local" when no OPENAI_API_KEY, else "openai".
TRANSCRIBE_BACKEND = os.getenv("TRANSCRIBE_BACKEND", "").lower()
if not TRANSCRIBE_BACKEND:
    TRANSCRIBE_BACKEND = "openai" if OPENAI_API_KEY else "local"

TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "small")  # faster-whisper model name if using local
EMOTION_BACKEND = os.getenv("EMOTION_BACKEND", "none").lower()  # none | local | remote
EMOTION_API_URL = os.getenv("EMOTION_API_URL")  # if EMOTION_BACKEND == "remote"
EMOTION_API_KEY = os.getenv("EMOTION_API_KEY")  # optional for remote
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
PORT = int(os.getenv("PORT", "3000"))
PREWARM_MODELS = os.getenv("PREWARM_MODELS", "false").lower() in ("1", "true", "yes")


BASE = Path(__file__).parent.resolve()
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("transcribe-backend")

app = FastAPI(title="Transcribe + Emotion backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_executor = ThreadPoolExecutor(max_workers=2)

_whisper_model = None
_whisper_lock = asyncio.Lock()

_local_ensemble = None
_emotion_lock = asyncio.Lock()

RECOMMENDATIONS_PATH = BASE / "emotion_recommendations.json"

_EMBEDDED_RECOMMENDATIONS = {
    "anger": [
        "Take a short break and practice slow, deep breathing for 60 seconds.",
        "Write down what triggered the anger to understand the cause clearly.",
        "Engage in a quick physical activity like a walk to release built-up tension."
    ],
    "disgust": [
        "Identify what specifically caused the feeling and whether it can be avoided in the future.",
        "Talk to someone you trust to express how you feel.",
        "Try grounding yourself by focusing on neutral sensory inputs (touch, smell, sound)."
    ],
    "fear": [
        "Pause and remind yourself that you are safe in the present moment.",
        "Break the fear into smaller thoughts and challenge the worst-case scenario.",
        "Do a calming activity such as meditation, soft music, or slow breathing."
    ],
    "joy": [
        "Celebrate the moment by writing it down or sharing it with someone.",
        "Engage in an activity that enhances your happiness, like music or hobbies.",
        "Use this positive energy to work on something meaningful to you."
    ],
    "neutral": [
        "Take a moment to reflect on how you're feeling physically and mentally.",
        "Do a small activity that brings clarity — journaling, stretching, or a short walk.",
        "Try to set a simple goal or intention for the next hour of your day."
    ],
    "sadness": [
        "Allow yourself to feel it—crying or journaling can be healthy outlets.",
        "Reach out to a close friend or family member and talk about what’s weighing on you.",
        "Do one small self-care activity such as drinking water, taking a warm shower, or stepping outside."
    ],
    "surprise": [
        "Pause and evaluate whether the surprise is positive or negative.",
        "Give yourself a moment to adjust before reacting or making decisions.",
        "If it’s positive, celebrate it; if it’s overwhelming, breathe and ground yourself."
    ]
}

RECOMMENDATIONS_MAP: Dict[str, Any] = {}
try:
    if RECOMMENDATIONS_PATH.exists():
        with open(RECOMMENDATIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in data.items():
                recs = v.get("recommendations") if isinstance(v, dict) else v
                if isinstance(recs, list):
                    RECOMMENDATIONS_MAP[k.lower()] = recs
    # Ensure fallback
    for k, v in _EMBEDDED_RECOMMENDATIONS.items():
        RECOMMENDATIONS_MAP.setdefault(k, v)
    logger.info("Loaded emotion recommendations (keys=%d).", len(RECOMMENDATIONS_MAP))
except Exception:
    logger.exception("Failed to load emotion_recommendations.json — falling back to embedded recommendations.")
    RECOMMENDATIONS_MAP = _EMBEDDED_RECOMMENDATIONS.copy()


def get_recommendations_for_emotion(emotion: Optional[str]):
   
    if not emotion:
        return []
    return RECOMMENDATIONS_MAP.get(emotion.lower(), [])



async def ensure_whisper_loaded():
   
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    async with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model

        def _load():
            from faster_whisper import WhisperModel  # type: ignore
            device = os.getenv("WHISPER_DEVICE", "cpu")
            model_name = os.getenv("TRANSCRIBE_MODEL", "small")
            return WhisperModel(model_name, device=device)

        loop = asyncio.get_running_loop()
        try:
            _whisper_model = await loop.run_in_executor(_executor, _load)
            logger.info("faster-whisper model loaded (lazy): %s on %s", os.getenv("TRANSCRIBE_MODEL"), os.getenv("WHISPER_DEVICE"))
        except Exception:
            logger.exception("Failed to load faster-whisper model")
            _whisper_model = None
            raise

    return _whisper_model


async def ensure_emotion_loaded():
    
    global _local_ensemble
    if _local_ensemble is not None:
        return _local_ensemble

    async with _emotion_lock:
        if _local_ensemble is not None:
            return _local_ensemble

        def _load():
            from emotion_model import ensemble as ensemble_fn  # type: ignore
            return ensemble_fn

        loop = asyncio.get_running_loop()
        try:
            _local_ensemble = await loop.run_in_executor(_executor, _load)
            logger.info("Emotion ensemble loaded (lazy)")
        except Exception:
            logger.exception("Failed to import local emotion_model")
            _local_ensemble = None
            raise

    return _local_ensemble

async def analyze_emotion(text: str) -> Optional[Dict[str, Any]]:
    if not text or EMOTION_BACKEND == "none":
        return None

    if EMOTION_BACKEND == "local":
        if _local_ensemble is None:
            try:
                await ensure_emotion_loaded()
            except Exception:
                logger.warning("EMOTION_BACKEND=local but local_ensemble not available after load attempt.")
                return {"error": "local ensemble not available"}

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: _local_ensemble(text, return_all=True))
            return result
        except Exception as e:
            logger.exception("Local emotion analysis failed")
            return {"error": f"local analysis failed: {e}"}

    if EMOTION_BACKEND == "remote":
        if not EMOTION_API_URL:
            logger.warning("EMOTION_BACKEND=remote but EMOTION_API_URL is not set.")
            return {"error": "remote API URL not configured"}
        try:
            headers = {"Content-Type": "application/json"}
            if EMOTION_API_KEY:
                headers["Authorization"] = f"Bearer {EMOTION_API_KEY}"
            payload = {"text": text}
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(EMOTION_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.exception("Remote emotion API returned non-2xx")
            return {
                "error": f"remote API error: {e.response.status_code}",
                "details": e.response.text,
            }
        except Exception as e:
            logger.exception("Remote emotion API call failed")
            return {"error": f"remote call failed: {e}"}

    return None


async def transcribe_with_faster_whisper(path: str) -> str:

    if _whisper_model is None:
        raise RuntimeError("Whisper model not loaded")

    loop = asyncio.get_running_loop()

    def _run():
        segments, info = _whisper_model.transcribe(path, beam_size=5)
        return "".join([seg.text for seg in segments])

    return await loop.run_in_executor(_executor, _run)


@app.get("/")
def root():
    return {"ok": True, "message": f"Transcribe + Emotion backend running (transcribe_backend={TRANSCRIBE_BACKEND})"}

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: Optional[str] = Form(None)):
    
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    
    try:
        contents = await file.read()
        size_mb = len(contents) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_MB:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({size_mb:.1f} MB). Max allowed {MAX_UPLOAD_MB} MB.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed reading uploaded file")
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e}")

   
    ext = Path(file.filename).suffix or ".mp3"
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / fname
    try:
        dest.write_bytes(contents)
    except Exception:
        logger.exception("Failed to save uploaded file to disk")
        

    transcription = ""
    raw = None


    if TRANSCRIBE_BACKEND == "local":
       
        if _whisper_model is None:
            try:
                await ensure_whisper_loaded()
            except Exception as e:
                logger.exception("Failed to lazy-load whisper model")
                raise HTTPException(status_code=500, detail=f"Local transcription model not available: {e}")

        if _whisper_model is None:
            logger.error("TRANSCRIBE_BACKEND=local but whisper_model not loaded")
            raise HTTPException(status_code=500, detail="Local transcription model not available")
        try:
            
            transcription = await transcribe_with_faster_whisper(str(dest))
            raw = {"backend": "local", "model": TRANSCRIBE_MODEL}
            logger.info("Local transcription complete (len=%d)", len(transcription))
        except Exception as e:
            logger.exception("Local transcription failed")
            raise HTTPException(status_code=500, detail=f"Local transcription failed: {e}")

   
    elif TRANSCRIBE_BACKEND == "openai":
        if not OPENAI_API_KEY:
            logger.error("TRANSCRIBE_BACKEND=openai but OPENAI_API_KEY not set")
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured for OpenAI backend")
        try:
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            async with httpx.AsyncClient(timeout=120.0) as client:
                files = {
                    "file": (file.filename or fname, contents, "application/octet-stream"),
                    "model": (None, "whisper-1"),
                }
               
                if language:
                    files["language"] = (None, language)
                resp = await client.post(url, headers=headers, files=files)
                resp.raise_for_status()
                data = resp.json()
                raw = data
                transcription = data.get("text") or data.get("transcription") or ""
                logger.info("OpenAI transcription complete (len=%d)", len(transcription))
        except httpx.HTTPStatusError as e:
            logger.exception("OpenAI API returned error")
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI API error: {e.response.status_code} {e.response.text}",
            )
        except Exception as e:
            logger.exception("Transcription failed")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    else:
        logger.error("Unsupported TRANSCRIBE_BACKEND: %s", TRANSCRIBE_BACKEND)
        raise HTTPException(status_code=500, detail=f"Unsupported TRANSCRIBE_BACKEND: {TRANSCRIBE_BACKEND}")

   
    emotion_result = None
    if transcription:
        try:
            emotion_result = await analyze_emotion(transcription)
        except Exception:
            logger.exception("Emotion analysis crashed")
            emotion_result = {"error": "emotion analysis failed"}

    
    if not emotion_result:
        emotion_result = {}

    final_emotion = None
    final_confidence = None
    if isinstance(emotion_result, dict):
        final_emotion = emotion_result.get("final_emotion") or emotion_result.get("finalLabel")
        final_confidence = emotion_result.get("confidence") or emotion_result.get("score")

    recommendations = get_recommendations_for_emotion(final_emotion)

    transcription = transcription.strip() if isinstance(transcription, str) else transcription

    resp_content = {
        "filename": fname,
        "transcription": transcription,
        "emotion": emotion_result,
        "final_emotion": final_emotion,
        "final_confidence": final_confidence,
        "recommendations": recommendations,
        "raw": raw,
    }
    return JSONResponse(status_code=200, content=resp_content)



@app.post("/api/upload")
async def transcribe_upload(file: UploadFile = File(...), language: Optional[str] = Form(None)):
    
    return await transcribe(file=file, language=language)


@app.post("/api/emotion-text")
async def emotion_text(payload: Dict[str, Any] = Body(...)):

    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing or empty 'text' field")

    if EMOTION_BACKEND == "none":
        raise HTTPException(
            status_code=500,
            detail="Emotion backend is disabled (EMOTION_BACKEND=none)",
        )

    result = await analyze_emotion(text)
    if not result:
        raise HTTPException(status_code=500, detail="Emotion analysis failed")


    final_emotion = None
    if isinstance(result, dict):
        final_emotion = result.get("final_emotion") or result.get("finalLabel")

    recs = get_recommendations_for_emotion(final_emotion)
    if isinstance(result, dict):
        result["recommendations"] = recs
    else:
        result = {"recommendations": recs}

    return JSONResponse(status_code=200, content=result)


@app.on_event("startup")
async def maybe_prewarm():
   
    if PREWARM_MODELS:
        if TRANSCRIBE_BACKEND == "local":
            asyncio.create_task(ensure_whisper_loaded())
        if EMOTION_BACKEND == "local":
            asyncio.create_task(ensure_emotion_loaded())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)

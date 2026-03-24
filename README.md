# FaceTrack SaaS (Micro SaaS Starter)

A deployable SaaS starter for social media creators:
- Landing page with product value and sample use-cases
- "Try Now" page with upload, progress tracking, preview, and download
- Python face-tracking pipeline (your provided logic adapted into a reusable function)
- Concurrent job handling for multiple customers

## Tech Stack
- **Backend**: FastAPI
- **Frontend**: Static HTML/CSS/JS
- **Video Processing**: OpenCV + MediaPipe + SciPy + FFmpeg

## Project Structure

```txt
app/
  main.py        # API, job manager, static hosting
  processor.py   # Face-tracking processing pipeline
static/
  index.html     # Landing page
  try.html       # Upload/progress/preview page
  css/styles.css
  js/try.js
data/
  uploads/       # runtime uploads
  outputs/       # processed videos
```

## Local Run

1. Install system dependency:
   - `ffmpeg` must be available in PATH.
2. Install python deps:
   ```bash
   pip install -r requirements.txt
   ```
3. Start app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
4. Open:
   - `http://localhost:8000/` (landing)
   - `http://localhost:8000/try.html` (try-now)

## API

- `POST /api/jobs` → upload video as multipart `file`
- `GET /api/jobs/{job_id}` → status/progress JSON
- `GET /api/jobs/{job_id}/result` → processed video download/stream

## Multi-customer handling

- Uses a `ThreadPoolExecutor` worker pool for background processing.
- `PROCESSOR_WORKERS` controls concurrency (default: `2`).
- Each uploaded video is isolated by a unique job id and temp workspace.

For production scale beyond a single instance, move job state and queue to shared infrastructure (Redis + Celery/RQ + object storage).

## Deploy (example: Render/Railway/Fly)

### Option A: Docker deployment
Use included Dockerfile and deploy to any container hosting platform.

### Option B: Native Python deployment
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Ensure FFmpeg is installed on host image.

## Notes

- The processing logic is kept intact; only input/output handling and progress callbacks were made SaaS-friendly.
- Uploaded files and outputs are stored locally in `data/` by default.

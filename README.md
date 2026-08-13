# Social-to-Story API

A lightweight FastAPI service that converts short social media updates (X/Twitter post text or URLs) into structured, publication-ready news narratives — modeled on the editorial style of government/tech policy announcements — returned as Markdown and JSON.

## Project Structure

```text
social-to-story-api/
├── app/
│   ├── main.py                # FastAPI app, CORS, router registration, /health
│   ├── core/
│   │   ├── config.py          # Settings (env vars) via Pydantic BaseSettings
│   │   └── prompts.py         # Editorial system prompt builder
│   ├── schemas/
│   │   ├── request.py         # StoryRequest
│   │   └── response.py        # StoryResponse / StoryData / TableItem
│   ├── services/
│   │   ├── extractor.py       # Resolves tweet_text or fetches post_url
│   │   └── llm_service.py     # Gemini call + structured output parsing
│   └── routers/
│       └── story.py           # POST /api/v1/generate-story
├── tests/
│   └── test_story_api.py
├── requirements.txt
├── .env.example
├── Dockerfile
├── .dockerignore
└── README.md
```

## 1. Local Setup (without Docker)

**Requirements:** Python 3.10+

```bash
# From the project root
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Copy the example environment file and fill in your Gemini API key:

```bash
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_actual_gemini_api_key
APP_ENV=development
PORT=8000
DEFAULT_MODEL=gemini-3.6-flash
```

## 2. Running Locally via Uvicorn

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API base URL: `http://localhost:8000`
- Local frontend: `http://localhost:8000`
- Interactive docs (Swagger UI): `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### Example request

```bash
curl -X POST http://localhost:8000/api/v1/generate-story \
  -H "Content-Type: application/json" \
  -d '{
    "tweet_text": "Ministry of IT & Telecom aggressively enabled guaranteed 17.7 Tbps+ bandwidth for Pakistan via additional fiber optic cables.",
    "author_handle": "@MoitOfficial",
    "output_format": "markdown"
  }'
```

### Download as Word document

Use `POST /api/v1/generate-story-docx` with the same request body to generate
and download a formatted `.docx` file containing the title, subtitle, source
context, summary table, and full story.

The local frontend at `http://localhost:8000` also provides download buttons for
organized Markdown (`.md`) and Word (`.docx`) exports after a story is generated.

```bash
curl -X POST http://localhost:8000/api/v1/generate-story-docx \
  -H "Content-Type: application/json" \
  -o story.docx \
  -d '{
    "tweet_text": "Pakistan has launched a new digital skills initiative to train 100,000 young people in cloud computing, artificial intelligence, cybersecurity, and software development.",
    "author_handle": "@MoitOfficial",
    "output_format": "markdown"
  }'
```

## 3. Running Tests

Tests mock the LLM service call, so **no live Gemini API key or network access is required** to run the suite:

```bash
pytest tests/ -v
```

## 4. Running with Docker

Build the image:

```bash
docker build -t social-to-story-api .
```

Run the container, passing your environment variables at runtime (the `.env` file is intentionally not baked into the image):

```bash
docker run -p 8000:8000 --env-file .env social-to-story-api
```

Or pass variables individually:

```bash
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_actual_gemini_api_key \
  -e DEFAULT_MODEL=gemini-3.6-flash \
  -e APP_ENV=production \
  social-to-story-api
```

The API will be available at `http://localhost:8000`, with the same `/docs` and `/health` endpoints as the local run.

## Notes

- CORS is currently configured to allow all origins for development convenience. Restrict `allow_origins` in `app/main.py` before deploying to production.
- `post_url` extraction relies on OpenGraph/Twitter meta tags being present in the fetched page. Some platforms (including X/Twitter itself, for logged-out/non-JS requests) may block this or return no usable description — in that case, supply `tweet_text` directly instead.
- The Dockerfile uses a multi-stage build (a `builder` stage installs dependencies into a virtual environment, and a slim `runtime` stage copies only that venv + app code) to keep the final image small, and runs as a non-root user.

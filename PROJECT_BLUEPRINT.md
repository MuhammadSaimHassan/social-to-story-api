\# Project Overview & Development Blueprint: Social-to-Story API

\#\# 1\. Project Goal & Scope  
The objective of this project is to build a lightweight, production-ready Python REST API using \*\*FastAPI\*\* and the \*\*Google GenAI SDK\*\* (or OpenAI/Anthropic fallback). The API accepts social media content (specifically X/Twitter post text or post URLs) as a JSON payload and returns a structured, publication-ready narrative article formatted in Markdown and JSON.

This API automates the exact editorial style and structure used in government/tech policy releases (e.g., MoITT announcements), transforming short updates into comprehensive, analytical news narratives.

\---

\#\# 2\. Core Architecture & Tech Stack

\- \*\*Language & Runtime:\*\* Python 3.10+  
\- \*\*API Framework:\*\* FastAPI \+ Uvicorn (ASGI)  
\- \*\*Data Validation & Schemas:\*\* Pydantic v2  
\- \*\*LLM Integration:\*\* \`google-genai\` (Gemini 2.5 Flash / Pro)  
\- \*\*HTTP & Extraction:\*\* \`httpx\` \+ \`beautifulsoup4\` (for URL post content scraping/fallback)  
\- \*\*Environment Management:\*\* \`python-dotenv\`  
\- \*\*Testing:\*\* \`pytest\` \+ FastAPI \`TestClient\`

\[Client / Webhook\] │ ▼ (HTTP POST /api/v1/generate-story) ┌────────────────────────────────────────────────────────┐ │ FastAPI Application │ │ ├─ API Route Handler (/routers/story.py) │ │ ├─ Request Validator (Pydantic Schema) │ │ ├─ Content Fetcher/Extractor (services/extractor.py) │ │ ├─ Editorial Prompt Builder (core/prompts.py) │ │ └─ LLM Client Service (services/llm\_service.py) │ └────────────────────────────────────────────────────────┘ │ ▼ (Structured Output Call) \[Gemini / LLM API\] │ ▼ \[Response: Structured JSON Payload with Story Markdown\]

\---

\#\# 3\. Recommended Project Structure

\`\`\`text  
social-to-story-api/  
├── app/  
│   ├── \_\_init\_\_.py  
│   ├── main.py                   \# App initialization & middleware  
│   ├── core/  
│   │   ├── \_\_init\_\_.py  
│   │   ├── config.py             \# Settings & Environment Variables  
│   │   └── prompts.py            \# Editorial system prompts  
│   ├── schemas/  
│   │   ├── \_\_init\_\_.py  
│   │   ├── request.py            \# Input Pydantic models  
│   │   └── response.py           \# Output Pydantic models  
│   ├── services/  
│   │   ├── \_\_init\_\_.py  
│   │   ├── extractor.py          \# Post text / URL parser  
│   │   └── llm\_service.py        \# Gemini client wrapper  
│   └── routers/  
│       ├── \_\_init\_\_.py  
│       └── story.py              \# Main POST /generate-story endpoint  
├── tests/  
│   ├── \_\_init\_\_.py  
│   ├── test\_extractor.py  
│   └── test\_story\_api.py  
├── .env.example  
├── Dockerfile  
├── requirements.txt  
├── PROJECT\_BLUEPRINT.md  
└── README.md

## **4\. API Specification**

### **Endpoint: `POST /api/v1/generate-story`**

#### **Request Payload (`StoryRequest`):**

JSON  
{  
  "tweet\_text": "To create runway for explosive IT exports growth and domestic economic activity, Ministry of IT & Telecom aggressively enabled guaranteed 17.7 Tbps+ bandwidth for Pakistan via additional fiber optic cables.",  
  "author\_handle": "@MoitOfficial",  
  "post\_url": "\[https://x.com/MoitOfficial/status/2085985308718563602\](https://x.com/MoitOfficial/status/2085985308718563602)",  
  "output\_format": "markdown"  
}

#### **Response Payload (`StoryResponse`):**

JSON  
{  
  "status": "success",  
  "data": {  
    "title": "Supercharging Digital Infrastructure: Pakistan Secures Guaranteed 17.7 Tbps Bandwidth",  
    "subtitle": "Ministry of IT & Telecom expands international fiber capacity to backstop 5G rollouts and export growth.",  
    "source\_context": "Official announcement by Ministry of IT & Telecom (@MoitOfficial)",  
    "summary\_table": \[  
      {  
        "pillar": "Guaranteed International Bandwidth",  
        "metric": "17.7+ Tbps",  
        "purpose": "Prevents single-cable outage bottlenecks and lowers latency."  
      }  
    \],  
    "story\_markdown": "\# Supercharging Digital Infrastructure...\\n\\n\#\#\# 1\. The Hook...\\n",  
    "word\_count": 620  
  }  
}

## **5\. Development Strategy (CRITICAL INSTRUCTION FOR CLAUDE)**

> ⚠️ **IMPORTANT INSTRUCTION FOR AI AGENT / CLAUDE:** Do **NOT** generate the entire application codebase in a single step or prompt. This project must be built **section by section, step by step**. Each section must be verified and confirmed working before moving to the next.

> Proceed strictly according to the following phase execution plan:

> 1. **Phase 1:** Environment & Configuration Setup (`config.py`, `requirements.txt`, `.env`)  
> 2. **Phase 2:** Data Schemas & Models (`schemas/request.py`, `schemas/response.py`)  
> 3. **Phase 3:** Editorial System Prompt Engine (`core/prompts.py`)  
> 4. **Phase 4:** Content Extractor & Fallback Service (`services/extractor.py`)  
> 5. **Phase 5:** LLM Service Integration (`services/llm_service.py`)  
> 6. **Phase 6:** API Router & Endpoint Wire-up (`routers/story.py` & `main.py`)  
> 7. **Phase 7:** Testing, Verification, and Containerization (`tests/`, `Dockerfile`)


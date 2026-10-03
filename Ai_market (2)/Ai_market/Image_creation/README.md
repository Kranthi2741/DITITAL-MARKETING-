# Auto Marketing Agent — Coffee Shop Project

An autonomous digital marketing pipeline: give it one prompt (e.g. "Create a
Diwali campaign for my coffee shop"), and 7 agents plan, generate, review,
retry if needed, write a caption, and prepare the post — no human steps in
between except the initial prompt.

## Project structure

```
coffee-marketing-agent/
├── backend/
│   ├── requirements.txt        # Python dependencies
│   ├── .env.example            # copy to .env, fill in your real keys
│   ├── .gitignore               # keeps .env and generated images out of git
│   ├── run.py                   # CLI runner (test the pipeline from terminal)
│   └── app/
│       ├── __init__.py
│       ├── state.py             # shared state schema passed between agents
│       ├── llm.py               # Gemini (reasoning/vision) + gpt-image-2 (image gen)
│       ├── graph.py             # LangGraph wiring: all 7 agents + retry loop
│       ├── main.py              # FastAPI app + WebSocket for live UI progress
│       └── agents/
│           ├── __init__.py
│           ├── planner.py            # Agent 1: understands the prompt
│           ├── strategist.py         # Agent 2: decides content strategy
│           ├── creative_director.py  # Agent 3: writes image brief, fixes failures
│           ├── image_generator.py    # Agent 4: generates the image (dumb tool node)
│           ├── quality_agent.py      # Agent 5: vision QA, approves or sends back
│           ├── content_agent.py      # Agent 6: writes caption + hashtags
│           └── publisher.py          # Agent 7: upload and publish to Instagram
└── frontend/
    └── index.html            # single-file UI: prompt box + live agent progress
```

## How the loop works

```
Planner -> Strategist -> Creative Director -> Image Generator -> Quality Agent
                                                                       |
                                                          approved? --yes--> Content Agent -> Publisher
                                                                       |
                                                                       no (score < 80)
                                                                       |
                                                          back to Creative Director
                                                          (with specific issues to fix)
                                                                       |
                                                          max 3 attempts, then stop
```

## Setup

```powershell
cd backend
copy .env.example .env
# edit .env and paste in your real keys:
#   GEMINI_API_KEY=...        (free at https://aistudio.google.com/apikey)
#   SINGULARITY_API_KEY=...   (for gpt-image-2 image generation)
#   CLOUDINARY_CLOUD_NAME=... and CLOUDINARY_UPLOAD_PRESET=...
#   INSTAGRAM_ACCESS_TOKEN=...
#   LINKEDIN_ACCESS_TOKEN=... and LINKEDIN_AUTHOR_URN=...

pip install -r requirements.txt
```

## Run — Option A: with the UI (recommended)

```powershell
uvicorn app.main:app --reload
```
Open **http://localhost:8000** in your browser. Type a prompt, hit Generate,
and watch each agent light up live, including retries if the Quality Agent
rejects an image.

## Run — Option B: from the terminal only

```powershell
python run.py "Create a Diwali campaign for my coffee shop"
```

## What's still a stub (not built yet)

- **Social publishing** — the Publisher uploads and publishes to Instagram and,
  when LinkedIn credentials are configured, uploads the image to LinkedIn's
  Images API and creates a LinkedIn Posts API image post. Instagram requires a
  Professional account and Cloudinary; LinkedIn requires an OAuth token and an
  author URN for a member or organization.
- **Business profile memory** — right now the business profile is hardcoded
  in `run.py` / not yet exposed in the UI. Add a form field or a saved
  profile file so you don't have to re-describe the coffee shop every time.
- **Scheduling / festival auto-detection** — the "look at the calendar and
  auto-launch a campaign" phase from the original plan.

## Security note

Never commit `.env` or paste real API keys anywhere outside your own
machine's environment variables. `.gitignore` is already set up to exclude
`.env` and generated images from git.

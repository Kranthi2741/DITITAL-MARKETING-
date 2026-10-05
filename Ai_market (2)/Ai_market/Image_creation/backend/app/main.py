"""
Backend API. Serves:
  - GET  /            -> the frontend UI
  - GET  /images/...  -> generated images so the browser can show them
  - WS   /ws/campaign -> send {"prompt": "..."} and receive a live stream of
                          {"node": "planner", "state": {...}} messages as each
                          agent runs, ending with {"node": "__done__", ...}

Run:
  cd backend
  uvicorn app.main:app --reload
"""

import os
import json
import asyncio
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
from typing import List
from datetime import date, datetime, timedelta
from openpyxl import load_workbook
from PIL import Image
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.graph import run_campaign, stream_campaign
from app import auth as auth_module

app = FastAPI()

# Initialise DB tables + seed admin on startup
try:
    auth_module.init_db()
except Exception as _db_err:
    print(f"[WARN] MySQL not available: {_db_err}. Auth endpoints will return 503.")
DATA_DIR = Path("app_data")
DATA_DIR.mkdir(exist_ok=True)
SCHEDULE_PATH = DATA_DIR / "schedule.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
SCHEDULE_STATUS_PATH = DATA_DIR / "schedule_status.json"
ASSET_INDEX_PATH = Path("asset_library") / "index.json"
UPLOAD_DIR = Path("uploaded_images")
UPLOAD_DIR.mkdir(exist_ok=True)

# Cancellation is checked between graph nodes. A provider call already in
# progress is allowed to finish, but no later agent (including Publisher) runs.
active_campaigns: dict[str, dict] = {}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_json(url: str, headers: dict | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _refresh_instagram(post_id: str) -> tuple[dict, str | None]:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        return {}, "INSTAGRAM_ACCESS_TOKEN is not configured"
    try:
        base = f"https://graph.instagram.com/{quote(post_id, safe='')}"
        fields = "id,caption,like_count,comments_count,permalink,timestamp,media_type"
        media = _get_json(f"{base}?fields={fields}&access_token={quote(token)}")
        metrics = {key: media.get(key, 0) for key in ("like_count", "comments_count")}
        comments = _get_json(f"{base}/comments?fields=id,text,username,timestamp,like_count&limit=50&access_token={quote(token)}")
        try:
            insights = _get_json(f"{base}/insights?metric=reach,saved,shares,views&access_token={quote(token)}")
            for item in insights.get("data", []):
                name = item.get("name")
                value = item.get("values", [{}])[-1].get("value", 0) if item.get("values") else item.get("value", 0)
                if name:
                    metrics[name] = value
        except Exception:
            # Basic like/comment fields are still useful when a metric is unavailable.
            pass
        return {"post_id": post_id, "url": media.get("permalink", ""), "metrics": metrics, "comments": comments.get("data", [])}, None
    except Exception as error:
        return {}, str(error)


def _refresh_linkedin(post_id: str) -> tuple[dict, str | None]:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        return {}, "LINKEDIN_ACCESS_TOKEN is not configured"
    try:
        version = os.environ.get("LINKEDIN_VERSION", "202601")
        headers = {"Authorization": f"Bearer {token}", "Linkedin-Version": version, "X-Restli-Protocol-Version": "2.0.0"}
        encoded = quote(post_id, safe="")
        data = _get_json(f"https://api.linkedin.com/rest/socialMetadata/{encoded}", headers)
        comments_data = _get_json(f"https://api.linkedin.com/rest/socialActions/{encoded}/comments?count=50", headers)
        reactions = data.get("reactionSummaries", {})
        comments = []
        for comment in comments_data.get("elements", []):
            comments.append({
                "id": comment.get("commentUrn") or comment.get("id"),
                "text": comment.get("message", {}).get("text", ""),
                "created": comment.get("created", {}).get("time"),
                "likes": comment.get("likesSummary", {}).get("totalLikes", 0),
            })
        return {"post_id": post_id, "url": "", "metrics": {
            "reactions": sum(item.get("count", 0) for item in reactions.values()) if isinstance(reactions, dict) else 0,
            "comments": data.get("commentsSummary", {}).get("aggregatedTotalComments", 0),
        }, "comments": comments}, None
    except Exception as error:
        return {}, str(error)


campaign_schedule = read_json(SCHEDULE_PATH, [])


def schedule_key(row: dict) -> str:
    return f"{row['date']}|{row['activity'].strip().casefold()}"


def matching_asset(row: dict, assets: list) -> dict | None:
    """Find the asset created for this exact calendar activity."""
    for asset in assets:
        if asset.get("scheduled_date") == row["date"] and asset.get("activity", "").strip().casefold() == row["activity"].strip().casefold():
            return asset
    return None


def run_scheduled_campaign(row: dict) -> None:
    """Create a missing due campaign in the background, without publishing it."""
    statuses = read_json(SCHEDULE_STATUS_PATH, {})
    key = schedule_key(row)
    try:
        result = run_campaign(row["activity"], scheduled_date=row["date"], auto_publish=True)
        asset = matching_asset(row, read_json(ASSET_INDEX_PATH, []))
        statuses[key] = {
            "status": "created" if asset else "failed",
            "updated_at": datetime.now().isoformat(),
            "campaign_id": asset.get("campaign_id") if asset else None,
            "detail": "Draft campaign created" if asset else "Quality review did not approve a campaign",
        }
    except Exception as error:
        statuses[key] = {"status": "failed", "updated_at": datetime.now().isoformat(), "detail": str(error)}
    write_json(SCHEDULE_STATUS_PATH, statuses)

GENERATED_DIR = "generated_images"
os.makedirs(GENERATED_DIR, exist_ok=True)
app.mount("/images", StaticFiles(directory=GENERATED_DIR), name="images")
os.makedirs("generated_campaigns", exist_ok=True)
app.mount("/campaigns", StaticFiles(directory="generated_campaigns"), name="campaigns")
os.makedirs("asset_library", exist_ok=True)
app.mount("/assets", StaticFiles(directory="asset_library"), name="assets")

FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html")


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_PATH)


@app.post("/api/schedule")
async def upload_schedule(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        return {"error": "Please upload an .xlsx or .xlsm file."}
    from io import BytesIO
    workbook = load_workbook(BytesIO(await file.read()), data_only=True)
    rows = list(workbook.active.iter_rows(values_only=True))
    if not rows:
        return {"error": "The workbook is empty."}
    headers = [str(value or "").strip().lower() for value in rows[0]]
    date_index = next((i for i, h in enumerate(headers) if h in {"date", "campaign date", "scheduled date"}), None)
    activity_index = next((i for i, h in enumerate(headers) if h in {"activity", "event", "campaign", "function"}), None)
    if date_index is None or activity_index is None:
        return {"error": "The first row must contain Date and Activity columns."}
    parsed = []
    for row in rows[1:]:
        if date_index >= len(row) or activity_index >= len(row) or not row[date_index] or not row[activity_index]:
            continue
        raw_date = row[date_index]
        try:
            scheduled = raw_date.date() if isinstance(raw_date, (datetime, date)) else datetime.fromisoformat(str(raw_date).strip()).date()
        except ValueError:
            scheduled = None
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"):
                try:
                    scheduled = datetime.strptime(str(raw_date).strip(), fmt).date()
                    break
                except ValueError:
                    continue
            if scheduled is None:
                continue
        parsed.append({"date": scheduled.isoformat(), "activity": str(row[activity_index]).strip()})
    global campaign_schedule
    campaign_schedule = parsed
    write_json(SCHEDULE_PATH, campaign_schedule)
    return {"rows": parsed, "count": len(parsed)}


@app.post("/api/images")
async def upload_images(images: List[UploadFile] = File(...)):
    """Store user photos for a campaign; only server-created IDs may be run."""
    uploaded = []
    for image in images:
        suffix = Path(image.filename or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            return {"error": "Upload JPG, PNG, or WebP image files only."}
        image_id = f"{uuid.uuid4().hex}{suffix}"
        output_path = UPLOAD_DIR / image_id
        data = await image.read()
        try:
            output_path.write_bytes(data)
            with Image.open(output_path) as opened:
                opened.verify()
        except Exception:
            output_path.unlink(missing_ok=True)
            return {"error": f"{image.filename or 'That file'} is not a valid image."}
        uploaded.append({"id": image_id, "name": image.filename})
    return {"images": uploaded, "count": len(uploaded)}


@app.get("/api/schedule")
def get_schedule():
    """Return every imported spreadsheet activity, not only today's jobs."""
    return {"rows": campaign_schedule, "count": len(campaign_schedule)}


@app.delete("/api/schedule")
def clear_schedule():
    """Remove spreadsheet data and cancel its active scheduled campaigns."""
    global campaign_schedule
    for run in active_campaigns.values():
        if run.get("scheduled"):
            run["cancelled"] = True
    campaign_schedule = []
    for path in (SCHEDULE_PATH, SCHEDULE_STATUS_PATH):
        path.unlink(missing_ok=True)
    return {"cleared": True}


@app.post("/api/campaigns/{run_id}/cancel")
def cancel_campaign(run_id: str):
    """Request cancellation of a live campaign after its current node returns."""
    run = active_campaigns.get(run_id)
    if not run:
        return {"cancelled": False, "detail": "Campaign is no longer running."}
    run["cancelled"] = True
    return {"cancelled": True, "detail": "Cancellation requested."}


@app.get("/api/calendar")
def get_calendar(month: str | None = None):
    """Calendar data grouped by ISO date; month is optional YYYY-MM."""
    rows = [row for row in campaign_schedule if not month or row["date"].startswith(month)]
    events = {}
    assets = read_json(ASSET_INDEX_PATH, [])
    statuses = read_json(SCHEDULE_STATUS_PATH, {})
    for row in rows:
        asset = matching_asset(row, assets)
        saved_status = statuses.get(schedule_key(row), {})
        status = "created" if asset else saved_status.get("status", "scheduled")
        events.setdefault(row["date"], []).append({
            "activity": row["activity"],
            "status": status,
            "detail": saved_status.get("detail", "Draft campaign created" if asset else "Waiting for its scheduled date"),
        })
    return {"events": events, "count": len(rows)}


@app.post("/api/schedule/run-due")
def run_due_schedule():
    """Reserve missing today/tomorrow campaigns for the live WebSocket runner."""
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assets = read_json(ASSET_INDEX_PATH, [])
    statuses = read_json(SCHEDULE_STATUS_PATH, {})
    queued = []
    for row in campaign_schedule:
        if row["date"] not in {today, tomorrow} or matching_asset(row, assets):
            continue
        key = schedule_key(row)
        if statuses.get(key, {}).get("status") == "queued":
            # A previous browser may have closed before attaching to the live
            # runner. Return the reservation so this login can resume it.
            queued.append(row)
            continue
        statuses[key] = {"status": "queued", "updated_at": datetime.now().isoformat(), "detail": "Creating scheduled draft"}
        queued.append(row)
    write_json(SCHEDULE_STATUS_PATH, statuses)
    return {"queued": queued, "count": len(queued)}


@app.get("/api/assets")
def get_assets():
    return {"assets": read_json(ASSET_INDEX_PATH, [])}


@app.get("/api/analytics")
def get_analytics():
    assets = read_json(ASSET_INDEX_PATH, [])
    approved = [asset for asset in assets if asset.get("quality_approved")]
    scores = [asset.get("quality_score") for asset in assets if isinstance(asset.get("quality_score"), (int, float))]
    campaign_rows = []
    for asset in reversed(assets):
        campaign_rows.append({
            "campaign_id": asset.get("campaign_id"),
            "name": asset.get("activity") or asset.get("campaign_plan", {}).get("festival") or "Campaign",
            "image": asset.get("assets", {}).get("image"),
            "social_posts": asset.get("social_posts", {}),
            "analytics": asset.get("analytics", {"latest": {}, "history": []}),
        })
    return {
        "campaigns": len(assets),
        "approved": len(approved),
        "average_quality": round(sum(scores) / len(scores), 1) if scores else None,
        "videos": sum(1 for asset in assets if asset.get("assets", {}).get("video")),
        "campaigns_detail": campaign_rows,
    }


@app.post("/api/analytics/refresh")
def refresh_analytics():
    """Fetch current engagement totals for all published campaign posts."""
    assets = read_json(ASSET_INDEX_PATH, [])
    refreshed_at = datetime.now().isoformat()
    refreshed = 0
    errors = []
    for asset in assets:
        social_posts = asset.get("social_posts", {})
        snapshot = {}
        for platform, fetcher in (("instagram", _refresh_instagram), ("linkedin", _refresh_linkedin)):
            post = social_posts.get(platform, {})
            if not post.get("post_id"):
                continue
            data, error = fetcher(post["post_id"])
            if error:
                errors.append({"campaign_id": asset.get("campaign_id"), "platform": platform, "error": error})
            elif data:
                snapshot[platform] = data
        if snapshot:
            analytics = asset.setdefault("analytics", {"latest": {}, "history": []})
            analytics["latest"] = {**analytics.get("latest", {}), **snapshot}
            analytics.setdefault("history", []).append({"refreshed_at": refreshed_at, **snapshot})
            refreshed += 1
    write_json(ASSET_INDEX_PATH, assets)
    return {"refreshed": refreshed, "refreshed_at": refreshed_at, "errors": errors}


@app.get("/api/integrations")
def get_integrations():
    """Expose connection state only; credentials never leave the server."""
    return {"integrations": [
        {"name": "Instagram", "connected": bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN"))},
        {"name": "LinkedIn", "connected": bool(os.environ.get("LINKEDIN_ACCESS_TOKEN") and os.environ.get("LINKEDIN_AUTHOR_URN"))},
        {"name": "Canva", "connected": Path("canva_tokens.json").exists()},
        {"name": "Cloudinary", "connected": bool(os.environ.get("CLOUDINARY_CLOUD_NAME") and os.environ.get("CLOUDINARY_UPLOAD_PRESET"))},
    ]}


DEFAULT_SETTINGS = {
    "workspace_name": "Marketing Workspace",
    "default_platform": "Instagram",
    "auto_publish": True,
    "brand_name": "",
    "brand_tagline": "",
    "brand_primary_color": "#283E53",
    "brand_accent_color": "#ED3237",
    "brand_cta_color": "#C5222B",
    "brand_font": "Modern Sans-Serif",
    "brand_logo_path": "",
}


@app.get("/api/settings")
def get_settings():
    return {**DEFAULT_SETTINGS, **read_json(SETTINGS_PATH, {})}


@app.put("/api/settings")
async def update_settings(payload: dict):
    allowed = {key: payload[key] for key in DEFAULT_SETTINGS if key in payload}
    settings = {**DEFAULT_SETTINGS, **read_json(SETTINGS_PATH, {}), **allowed}
    write_json(SETTINGS_PATH, settings)
    return settings


@app.post("/api/settings/logo")
async def upload_logo(logo: UploadFile = File(...)):
    suffix = Path(logo.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return {"error": "Upload a PNG, JPG, WebP, or SVG logo file."}
    logo_dir = DATA_DIR / "brand"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo_path = logo_dir / f"logo{suffix}"
    data = await logo.read()
    try:
        logo_path.write_bytes(data)
        if suffix != ".svg":
            with Image.open(logo_path) as img:
                img.verify()
    except Exception:
        logo_path.unlink(missing_ok=True)
        return {"error": "That file is not a valid image."}
    settings = {**DEFAULT_SETTINGS, **read_json(SETTINGS_PATH, {}), "brand_logo_path": str(logo_path)}
    write_json(SETTINGS_PATH, settings)
    return {"logo_path": str(logo_path), "logo_url": f"/brand-logo"}


@app.get("/api/settings/logo")
def get_logo_status():
    settings = {**DEFAULT_SETTINGS, **read_json(SETTINGS_PATH, {})}
    path = settings.get("brand_logo_path", "")
    exists = bool(path and Path(path).exists())
    return {"has_logo": exists, "logo_url": "/brand-logo" if exists else None}


@app.get("/brand-logo")
def serve_logo():
    settings = {**DEFAULT_SETTINGS, **read_json(SETTINGS_PATH, {})}
    path = settings.get("brand_logo_path", "")
    if path and Path(path).exists():
        return FileResponse(path)
    default = Path("assets") / "prorithm_logo.png"
    if default.exists():
        return FileResponse(str(default))
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="No logo configured")


# Node names in the order a UI would want to display them as a checklist
NODE_LABELS = {
    "planner": "Planner",
    "strategist": "Strategist",
    "creative_director": "Creative Director",
    "image_generator": "Image Generator",
    "quality_agent": "Quality Agent",
    "content_agent": "Content Agent",
    "compositor": "Compositor",
    "publisher": "Publisher",
}


def build_log_message(node_name: str, node_state: dict) -> str:
    """Turn a node's output into a human-readable one-line log message."""
    if node_name == "planner":
        plan = node_state.get("campaign_plan", {})
        return f"Understood request — festival: {plan.get('festival')}, tone: {plan.get('tone')}, platform: {plan.get('platform')}"
    if node_name == "strategist":
        strat = node_state.get("marketing_strategy", {})
        direction = node_state.get("design_direction", {})
        tagline = node_state.get("rhyming_tagline", "")
        suffix = f' — rhyme: "{tagline}"' if tagline else ""
        return f"Selected {direction.get('style', 'creative')} style with 3 concepts — audience: {strat.get('target_audience')}{suffix}"
    if node_name == "creative_director":
        brief = node_state.get("creative_brief", {})
        return f"Wrote creative brief — composition: {brief.get('composition', '')[:80]}"
    if node_name == "image_generator":
        return f"Generated image (attempt {node_state.get('retry_count', 0)})"
    if node_name == "quality_agent":
        score = node_state.get("quality_score")
        approved = node_state.get("quality_approved")
        if approved:
            return f"Reviewed image — score {score}/100 — APPROVED"
        issues = node_state.get("quality_issues", [])
        return f"Reviewed image — score {score}/100 — REJECTED ({', '.join(issues[:2])}) — sending back for fixes"
    if node_name == "content_agent":
        return f"Wrote caption and {len(node_state.get('hashtags', []))} hashtags"
    if node_name == "compositor":
        return "Composited infographic layout onto background image"
    if node_name == "publisher":
        destinations = []
        if node_state.get("instagram_published"):
            destinations.append(f"Instagram ({node_state.get('instagram_post_id')})")
        if node_state.get("linkedin_published"):
            destinations.append(f"LinkedIn ({node_state.get('linkedin_post_id')})")
        if destinations:
            message = "Published to " + " and ".join(destinations)
            if node_state.get("instagram_error"):
                message += f"; Instagram failed — {node_state['instagram_error']}"
            if node_state.get("linkedin_error"):
                message += f"; LinkedIn failed — {node_state['linkedin_error']}"
            return message
        errors = "; ".join(filter(None, [node_state.get("publish_error"), node_state.get("linkedin_error")]))
        return f"Publishing failed — {errors or 'unknown error'}"
    return "Working..."


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _require_token(request):
    """Extract and validate Bearer token from Authorization header."""
    from fastapi import Request, HTTPException
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    data = auth_module.decode_token(auth_header[7:])
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return data


# ── Auth routes ───────────────────────────────────────────────────────────────

from fastapi import Request, HTTPException


@app.post("/api/auth/login")
async def login(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    user = auth_module.get_user_by_email(email)
    if not user or not auth_module.verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth_module.create_token(user["id"], user["email"], user["role"])
    return {
        "token": token,
        "email": user["email"],
        "role": user["role"],
        "must_change": bool(user["must_change"]),
    }


@app.post("/api/auth/setup-password")
async def setup_password(request: Request, payload: dict):
    claims = _require_token(request)
    new_password = payload.get("password") or ""
    if not auth_module.password_strong(new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters with uppercase, lowercase, digit, and special character.")
    auth_module.update_password(claims["sub"], new_password)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(request: Request):
    claims = _require_token(request)
    user = auth_module.get_user_by_id(claims["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user["id"], "email": user["email"], "role": user["role"], "must_change": bool(user["must_change"])}


# ── Admin-only user management ────────────────────────────────────────────────

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    claims = _require_token(request)
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {"users": auth_module.list_users()}


@app.post("/api/admin/users")
async def admin_create_user(request: Request, payload: dict):
    claims = _require_token(request)
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    email = (payload.get("email") or "").strip().lower()
    temp_password = payload.get("temp_password") or ""
    if not email or not temp_password:
        raise HTTPException(status_code=400, detail="email and temp_password are required")
    if auth_module.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Email already exists")
    user = auth_module.create_user(email, temp_password)
    return {"ok": True, "user": user}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(request: Request, user_id: int):
    claims = _require_token(request)
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    auth_module.delete_user(user_id)
    return {"ok": True}


@app.post("/api/logs/campaign")
async def log_campaign(request: Request, payload: dict):
    claims = _require_token(request)
    try:
        auth_module.log_campaign(
            user_id=claims["sub"],
            email=claims["email"],
            role=claims["role"],
            prompt=payload.get("prompt", ""),
            image_count=int(payload.get("image_count", 0)),
        )
    except Exception:
        pass  # never block the campaign
    return {"ok": True}


@app.get("/api/admin/logs")
async def admin_get_logs(request: Request):
    claims = _require_token(request)
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {"logs": auth_module.list_campaign_logs()}


@app.websocket("/ws/campaign")
async def campaign_socket(websocket: WebSocket):
    await websocket.accept()
    run_id = None
    try:
        data = await websocket.receive_json()
        run_id = str(data.get("run_id") or "")
        prompt = data.get("prompt", "")
        auto_publish = data.get("auto_publish", True)
        requested_campaigns = data.get("scheduled_campaigns", [])
        uploaded_image_ids = [str(image_id) for image_id in data.get("uploaded_images", [])]

        # Merge saved brand kit into business_profile so every campaign
        # automatically uses the brand colors, font, name and tagline.
        saved_settings = read_json(SETTINGS_PATH, {})
        brand_kit = {
            "name":          saved_settings.get("brand_name", ""),
            "tagline":       saved_settings.get("brand_tagline", ""),
            "primary_color": saved_settings.get("brand_primary_color", ""),
            "accent_color":  saved_settings.get("brand_accent_color", ""),
            "cta_color":     saved_settings.get("brand_cta_color", ""),
            "font":          saved_settings.get("brand_font", ""),
        }
        business_profile = {**brand_kit, **data.get("business_profile", {})}

        today = date.today()
        scheduled = [row for row in campaign_schedule if row["date"] in {today.isoformat(), (today + timedelta(days=1)).isoformat()}]
        # The browser may explicitly request the already-reserved rows so the
        # automatic schedule path has the same live progress UI as Generate.
        requested_keys = {schedule_key(row) for row in requested_campaigns if isinstance(row, dict) and row.get("date") and row.get("activity")}
        requested = [row for row in campaign_schedule if schedule_key(row) in requested_keys]
        if not prompt and not scheduled and not requested and not uploaded_image_ids:
            await websocket.send_json({"node": "__error__", "message": "No prompt given."})
            await websocket.close()
            return

        uploaded_campaigns = []
        for image_id in uploaded_image_ids:
            candidate = (UPLOAD_DIR / Path(image_id).name).resolve()
            if candidate.parent != UPLOAD_DIR.resolve() or not candidate.is_file():
                await websocket.send_json({"node": "__error__", "message": "An uploaded image was not found. Upload it again and retry."})
                return
            uploaded_campaigns.append({"date": today.isoformat(), "activity": prompt or "Create a social media post for this photo", "source_image_path": str(candidate)})

        campaigns = uploaded_campaigns or requested or scheduled or [{"date": today.isoformat(), "activity": prompt}]
        run_id = run_id or f"campaign-{datetime.now().timestamp()}"
        active_campaigns[run_id] = {"cancelled": False, "scheduled": bool(requested or scheduled)}
        for campaign_index, campaign in enumerate(campaigns):
            if active_campaigns[run_id]["cancelled"]:
                await websocket.send_json({"node": "__cancelled__", "message": "Campaign cancelled."})
                return
            await websocket.send_json({"node": "__campaign_start__", "campaign": campaign, "index": campaign_index, "total": len(campaigns)})
            final_state = {}
            steps = iter(stream_campaign(
                campaign["activity"], business_profile,
                scheduled_date=campaign["date"], auto_publish=auto_publish,
                source_image_path=campaign.get("source_image_path"),
            ))
            while True:
                if active_campaigns[run_id]["cancelled"]:
                    await websocket.send_json({"node": "__cancelled__", "message": "Campaign cancelled. No further agents will run."})
                    return
                step = await asyncio.to_thread(next, steps, None)
                if step is None:
                    break
                node_name, node_state = step
                final_state.update(node_state)
                image_url = None
                video_url = None
                if node_state.get("generated_image_path"):
                    filename = os.path.basename(node_state["generated_image_path"])
                    image_url = f"/images/{filename}"
                if node_state.get("generated_video_path"):
                    campaign_folder = Path(node_state["generated_video_path"]).parent.name
                    video_url = f"/campaigns/{campaign_folder}/motion_graphic.mp4"
                await websocket.send_json({
                    "node": node_name,
                    "label": NODE_LABELS.get(node_name, node_name),
                    "log": build_log_message(node_name, node_state),
                    "state": {
                        "campaign": campaign,
                        "campaign_plan": node_state.get("campaign_plan"),
                        "costar_brief": node_state.get("costar_brief"),
                        "marketing_strategy": node_state.get("marketing_strategy"),
                        "design_direction": node_state.get("design_direction"),
                        "selected_concept": node_state.get("selected_concept"),
                        "creative_brief": node_state.get("creative_brief"),
                        "image_prompt": node_state.get("image_prompt"),
                        "quality_score": node_state.get("quality_score"),
                        "quality_approved": node_state.get("quality_approved"),
                        "quality_issues": node_state.get("quality_issues"),
                        "retry_count": node_state.get("retry_count"),
                        "caption": node_state.get("caption"),
                        "hashtags": node_state.get("hashtags"),
                        "image_url": image_url,
                        "video_url": video_url,
                        "source_files_dir": node_state.get("source_files_dir"),
                        "asset_library_id": node_state.get("asset_library_id"),
                        "asset_version": node_state.get("asset_version"),
                        "asset_library_path": node_state.get("asset_library_path"),
                        "instagram_published": node_state.get("instagram_published"),
                        "instagram_error": node_state.get("instagram_error"),
                        "linkedin_published": node_state.get("linkedin_published"),
                        "linkedin_post_id": node_state.get("linkedin_post_id"),
                        "linkedin_error": node_state.get("linkedin_error"),
                    },
                })
            if requested:
                statuses = read_json(SCHEDULE_STATUS_PATH, {})
                key = schedule_key(campaign)
                created = bool(final_state.get("asset_library_id"))
                statuses[key] = {
                    "status": "created" if created else "failed",
                    "updated_at": datetime.now().isoformat(),
                    "campaign_id": final_state.get("asset_library_id"),
                    "detail": "Draft campaign created" if created else "Campaign did not complete approval",
                }
                write_json(SCHEDULE_STATUS_PATH, statuses)
            await websocket.send_json({"node": "__campaign_done__", "campaign": campaign, "index": campaign_index})

        await websocket.send_json({"node": "__done__", "message": "Campaign finished."})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"node": "__error__", "message": str(e)})
    finally:
        if run_id:
            active_campaigns.pop(run_id, None)
        await websocket.close()

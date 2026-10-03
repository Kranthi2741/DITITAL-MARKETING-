import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.state import CampaignState


def _update_asset_record(campaign_id: str, updates: dict) -> None:
    """Attach publishing identifiers to the matching asset-library record."""
    index_path = Path("asset_library") / "index.json"
    if not campaign_id or not index_path.exists():
        return
    try:
        records = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for record in records:
        if record.get("campaign_id") == campaign_id:
            record.setdefault("social_posts", {}).update(updates)
            record.setdefault("analytics", {"latest": {}, "history": []})
            record["analytics"].setdefault("latest", {})
            record["analytics"].setdefault("history", [])
            break
    index_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def _cloudinary_upload(image_path: str) -> str:
    """Upload the local image so Instagram can fetch it over HTTPS."""
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    upload_preset = os.environ.get("CLOUDINARY_UPLOAD_PRESET")
    if not cloud_name or not upload_preset:
        raise RuntimeError("CLOUDINARY_CLOUD_NAME and CLOUDINARY_UPLOAD_PRESET are required")

    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    image_bytes = Path(image_path).read_bytes()
    fields = {"upload_preset": upload_preset}
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{Path(image_path).name}"\r\n'.encode())
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(image_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    request = Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        result = json.loads(response.read().decode())
    if not result.get("secure_url"):
        raise RuntimeError(f"Cloudinary upload failed: {result}")

    # Instagram accepts a public HTTPS image URL; normalize to square JPEG.
    return result["secure_url"].replace(
        "/image/upload/", "/image/upload/c_fill,w_1080,h_1080,ar_1:1,g_auto,f_jpg/"
    )


def _instagram_publish(image_url: str, caption: str) -> str:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN is required")

    create_data = urlencode({"image_url": image_url, "caption": caption, "access_token": token}).encode()
    try:
        with urlopen(Request("https://graph.instagram.com/me/media", data=create_data, method="POST"), timeout=60) as response:
            container = json.loads(response.read().decode())
    except HTTPError as error:
        details = error.read().decode(errors="replace")
        raise RuntimeError(f"Instagram media container failed (HTTP {error.code}): {details}") from error
    creation_id = container.get("id")
    if not creation_id:
        raise RuntimeError(f"Instagram media container failed: {container}")

    status = "IN_PROGRESS"
    for _ in range(30):
        time.sleep(2)
        query = urlencode({"fields": "status_code,status", "access_token": token})
        try:
            with urlopen(f"https://graph.instagram.com/{creation_id}?{query}", timeout=60) as response:
                status_data = json.loads(response.read().decode())
        except HTTPError as error:
            details = error.read().decode(errors="replace")
            raise RuntimeError(f"Instagram status check failed (HTTP {error.code}): {details}") from error
        status = status_data.get("status_code") or status_data.get("status")
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram processing failed: {status_data}")
    if status != "FINISHED":
        raise RuntimeError("Instagram processing timed out after 60 seconds")

    publish_data = urlencode({"creation_id": creation_id, "access_token": token}).encode()
    try:
        with urlopen(Request("https://graph.instagram.com/me/media_publish", data=publish_data, method="POST"), timeout=60) as response:
            published = json.loads(response.read().decode())
    except HTTPError as error:
        details = error.read().decode(errors="replace")
        raise RuntimeError(f"Instagram publish failed (HTTP {error.code}): {details}") from error
    if not published.get("id"):
        raise RuntimeError(f"Instagram publish failed: {published}")
    return published["id"]


def _linkedin_publish(image_path: str, caption: str) -> str:
    """Upload the final image to LinkedIn and publish an organic image post."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    author = os.environ.get("LINKEDIN_AUTHOR_URN")
    version = os.environ.get("LINKEDIN_VERSION", "202601")
    if not token or not author:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_URN are required")

    headers = {
        "Authorization": f"Bearer {token}",
        "Linkedin-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    init_body = json.dumps({"initializeUploadRequest": {"owner": author}}).encode()
    request = Request(
        "https://api.linkedin.com/rest/images?action=initializeUpload",
        data=init_body,
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode())
    upload = result.get("value", {})
    upload_url = upload.get("uploadUrl")
    image_urn = upload.get("image")
    if not upload_url or not image_urn:
        raise RuntimeError(f"LinkedIn image initialization failed: {result}")

    image_request = Request(
        upload_url,
        data=Path(image_path).read_bytes(),
        headers={"Content-Type": "image/png"},
        method="PUT",
    )
    with urlopen(image_request, timeout=90) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"LinkedIn image upload failed: HTTP {response.status}")

    post_body = json.dumps({
        "author": author,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {"media": {"id": image_urn}},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }).encode()
    post_headers = {**headers, "Content-Type": "application/json"}
    post_request = Request(
        "https://api.linkedin.com/rest/posts",
        data=post_body,
        headers=post_headers,
        method="POST",
    )
    with urlopen(post_request, timeout=60) as response:
        raw_body = response.read()
        response_body = json.loads(raw_body.decode()) if raw_body else {}
        post_id = response.headers.get("x-restli-id") or response_body.get("id")
    if not post_id:
        raise RuntimeError(f"LinkedIn post response did not include an ID: {response_body}")
    return post_id


def publisher_node(state: CampaignState) -> CampaignState:
    caption = state.get("caption", "")
    hashtags = state.get("hashtags", [])
    full_caption = f"{caption}\n\n{' '.join(hashtags)}".strip()
    result = {
        "published": False,
        "publish_platform": "instagram",
        "publish_id": "",
        "publish_error": "",
        "instagram_published": False,
        "instagram_post_id": "",
        "instagram_error": "",
        "linkedin_published": False,
        "linkedin_post_id": "",
        "linkedin_error": "",
    }

    if not state.get("auto_publish", True):
        result.update({
            "publish_platform": "draft",
            "publish_error": "Publishing skipped: scheduled campaigns are saved as drafts.",
        })
        _update_asset_record(state.get("asset_library_id", ""), {"status": "draft"})
        return result

    try:
        image_url = _cloudinary_upload(state["generated_image_path"])
        instagram_id = _instagram_publish(image_url, full_caption)
        result.update({"instagram_published": True, "instagram_post_id": instagram_id, "publish_id": instagram_id})
    except Exception as error:
        result["instagram_error"] = str(error)
        result["publish_error"] = f"Instagram: {error}"

    # LinkedIn is intentionally held back for this phase. Keep the fields in
    # the state so its connector can be enabled later without changing the UI.
    result["linkedin_error"] = "LinkedIn publishing is disabled until enabled in integrations."

    result["published"] = result["instagram_published"] or result["linkedin_published"]
    _update_asset_record(state.get("asset_library_id", ""), {
        "instagram": {"post_id": result["instagram_post_id"], "url": "", "published": result["instagram_published"]},
        "linkedin": {"post_id": result["linkedin_post_id"], "url": "", "published": result["linkedin_published"]},
    })
    return result

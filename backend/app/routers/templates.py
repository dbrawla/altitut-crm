"""Template endpoints — port of cmd/templates.go."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app import auth, db, tmpl
from app.utils import bad_request, not_found, ok

router = APIRouter(tags=["templates"])

_TYPES = {"campaign", "campaign_visual", "tx"}


@router.get("/api/templates", dependencies=[auth.require("templates:get")])
async def get_templates(no_body: bool = False) -> dict[str, Any]:
    return ok(await db.fetch("get-templates", 0, no_body, ""))


@router.get("/api/templates/{tpl_id}", dependencies=[auth.require("templates:get")])
async def get_template(tpl_id: int) -> dict[str, Any]:
    rows = await db.fetch("get-templates", tpl_id, False, "")
    if not rows:
        raise not_found("template not found")
    return ok(rows[0])


@router.get("/api/templates/{tpl_id}/preview", dependencies=[auth.require("templates:get")])
async def preview_template(tpl_id: int) -> dict[str, Any]:
    rows = await db.fetch("get-templates", tpl_id, False, "")
    if not rows:
        raise not_found("template not found")
    t = rows[0]
    # Render with a dummy campaign, like the original's template preview.
    camp = {
        "uuid": tmpl.DUMMY_UUID,
        "name": "Sample campaign",
        "subject": "Sample campaign subject",
        "from_email": "noreply@yoursite.com",
        "body": "<p>Hello there!</p>"
        "<p>This is a sample campaign body rendered into the template.</p>",
        "content_type": "html",
        "template_body": t["body"],
    }
    if t["type"] == "tx":
        camp["body"], camp["template_body"] = t["body"], ""
    return ok({"body": await tmpl.render_campaign_preview(camp, None)})


class PreviewBody(BaseModel):
    body: str = ""
    template_type: str = "campaign"


@router.post("/api/templates/preview", dependencies=[auth.require("templates:get")])
async def preview_template_body(payload: PreviewBody) -> dict[str, Any]:
    """Preview an unsaved template body straight from the editor."""
    if not payload.body.strip():
        raise bad_request("empty template body")

    camp = {
        "uuid": tmpl.DUMMY_UUID,
        "name": "Sample campaign",
        "subject": "Sample campaign subject",
        "from_email": "noreply@yoursite.com",
        "body": "<p>Hello there!</p>"
        "<p>This is a sample campaign body rendered into the template.</p>",
        "content_type": "html",
        "template_body": payload.body,
    }
    if payload.template_type == "tx":
        camp["body"], camp["template_body"] = payload.body, ""

    try:
        return ok({"body": await tmpl.render_campaign_preview(camp, None)})
    except Exception as e:
        raise bad_request(f"error rendering template: {e}") from None


class TemplatePayload(BaseModel):
    name: str
    type: str = "campaign"
    subject: str = ""
    body: str = ""
    body_source: str | None = None


@router.post("/api/templates", dependencies=[auth.require("templates:manage")])
async def create_template(payload: TemplatePayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise bad_request("invalid template name")
    if payload.type not in _TYPES:
        raise bad_request("invalid template type")
    tpl_id = await db.fetchval(
        "create-template", payload.name.strip(), payload.type, payload.subject,
        payload.body, payload.body_source,
    )
    return ok((await db.fetch("get-templates", tpl_id, False, ""))[0])


@router.put("/api/templates/{tpl_id}", dependencies=[auth.require("templates:manage")])
async def update_template(tpl_id: int, payload: TemplatePayload) -> dict[str, Any]:
    await db.execute(
        "update-template", tpl_id, payload.name.strip(), payload.subject,
        payload.body, payload.body_source or "",
    )
    rows = await db.fetch("get-templates", tpl_id, False, "")
    if not rows:
        raise not_found("template not found")
    return ok(rows[0])


@router.put("/api/templates/{tpl_id}/default", dependencies=[auth.require("templates:manage")])
async def set_default_template(tpl_id: int) -> dict[str, Any]:
    rows = await db.fetch("get-templates", tpl_id, True, "")
    if not rows:
        raise not_found("template not found")
    if rows[0]["type"] not in ("campaign", "campaign_visual"):
        raise bad_request("only campaign templates can be set as default")
    await db.execute("set-default-template", tpl_id)
    return ok(True)


@router.delete("/api/templates/{tpl_id}", dependencies=[auth.require("templates:manage")])
async def delete_template(tpl_id: int) -> dict[str, Any]:
    deleted = await db.fetchval("delete-template", tpl_id)
    if not deleted:
        # The query refuses to delete the default or the last remaining template.
        raise bad_request("cannot delete the default or only template")
    return ok(True)

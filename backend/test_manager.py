"""No-DB checks for the send engine and the template call convention.

Run from backend/:  python test_manager.py   (or pytest test_manager.py)

These cover the three bugs that made sent campaigns wrong and are cheap to
regress: Go-style niladic template funcs, SMTP block selection, and the
route ordering that /subscription/optin/<uuid> depends on.
"""

from starlette.testclient import TestClient

import app.main as m
from app import manager, settings, tmpl

client = TestClient(m.app)


def test_niladic_template_funcs_render_values():
    """Go auto-calls niladic funcs, Jinja does not — `{{ UnsubscribeURL }}`
    used to render '<function ... at 0x...>' into every sent email."""
    settings.cache["app.root_url"] = "https://mail.example.com"
    settings.cache["privacy.disable_tracking"] = False

    camp = {
        "uuid": "11111111-1111-1111-1111-111111111111",
        "subject": "Hi {{ .Subscriber.FirstName }}",
        "body": '<a href="{{ UnsubscribeURL }}">go</a>{{ TrackView }}',
        "content_type": "richtext",
        "template_body": "",
    }
    sub = {
        "uuid": "22222222-2222-2222-2222-222222222222",
        "email": "a@b.c",
        "name": "Ada Lovelace",
        "status": "enabled",
        "attribs": {},
    }

    import asyncio

    subject, html, _ = asyncio.run(tmpl.render_message(camp, sub, preview=True))

    assert subject == "Hi Ada"
    assert "function" not in html and "0x" not in html
    assert "https://mail.example.com/subscription/" in html


def test_smtp_block_selection():
    settings.cache["smtp"] = [
        {"enabled": False, "host": "off.example.com", "name": ""},
        {"enabled": True, "host": "default.example.com", "name": ""},
        {"enabled": True, "host": "named.example.com", "name": "email-bulk"},
    ]
    # "email" (the default messenger) resolves to the first *enabled* block.
    assert manager._smtp_block("email")["host"] == "default.example.com"
    assert manager._smtp_block("email-bulk")["host"] == "named.example.com"
    # An unknown name falls back rather than silently dropping the message.
    assert manager._smtp_block("nope")["host"] == "default.example.com"

    settings.cache["smtp"] = [{"enabled": False, "host": "x", "name": ""}]
    assert manager._smtp_block("email") is None


def test_optin_route_is_matched_before_the_two_uuid_route():
    """/subscription/{camp_uuid}/{sub_uuid} must be registered after the opt-in
    routes; if that order flips, opt-in 400s with camp_uuid='optin'."""
    from app.routers import public

    paths = [r.path for r in public.router.routes if r.path.startswith("/subscription/")]
    assert paths.index("/subscription/optin/{sub_uuid}") < paths.index(
        "/subscription/{camp_uuid}/{sub_uuid}"
    )


def test_tracking_pixel_always_returns_an_image():
    """Mail clients must never see an error body from the pixel endpoint."""
    r = client.get("/campaign/not-a-uuid/also-not-a-uuid/px.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/gif"


if __name__ == "__main__":
    for fn in (
        test_niladic_template_funcs_render_values,
        test_smtp_block_selection,
        test_optin_route_is_matched_before_the_two_uuid_route,
        test_tracking_pixel_always_returns_an_image,
    ):
        fn()
        print(f"  ok  {fn.__name__}")
    print("MANAGER OK")

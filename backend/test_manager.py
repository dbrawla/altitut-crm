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


def test_list_unsubscribe_header_is_not_encoded():
    """aiosmtplib re-folds at 78 chars and would turn the unsubscribe URL into
    an RFC 2047 encoded-word that no mail client can action."""
    url = (
        "<https://mail.example.com/subscription/"
        "11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222>"
    )
    msg = manager._build(
        "a@b.c", "Subject", "<p>hi</p>", "hi", "from@x.y",
        [{"List-Unsubscribe": url, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}],
    )
    raw = msg.as_bytes().decode()
    assert f"List-Unsubscribe: {url}" in raw
    assert "=?utf-8?" not in raw.split("\r\n\r\n", 1)[0]

    # A non-ASCII subject must still be encoded rather than sent as raw 8-bit.
    msg2 = manager._build("a@b.c", "Naïve — ünïcode", "<p>hi</p>", "hi", "from@x.y")
    hdrs = msg2.as_bytes().decode().split("\r\n\r\n", 1)[0]
    assert "=?utf-8?" in hdrs


def test_campaign_headers_carry_bounce_correlation_ids():
    settings.cache["privacy.unsubscribe_header"] = True
    settings.cache["app.root_url"] = "https://mail.example.com"
    camp = {"uuid": "aaaaaaaa-1111-1111-1111-111111111111", "headers": [{"X-Custom": "keep"}]}
    sub = {"uuid": "bbbbbbbb-2222-2222-2222-222222222222"}

    merged: dict[str, str] = {}
    for h in manager.campaign_headers(camp, sub):
        merged.update(h)

    assert merged["X-Listmonk-Campaign"] == camp["uuid"]
    assert merged["X-Listmonk-Subscriber"] == sub["uuid"]
    assert merged["X-Custom"] == "keep"  # campaign's own headers survive
    assert merged["List-Unsubscribe"].startswith("<https://mail.example.com/subscription/")


def test_bounce_classification():
    from app import bouncescan

    hard = b"Final-Recipient: rfc822; x@y.z\r\nStatus: 5.1.1\r\nmailbox unavailable"
    soft = b"Final-Recipient: rfc822; x@y.z\r\nStatus: 4.2.2\r\nover quota"
    assert bouncescan.classify(hard)[0] == "hard"
    assert bouncescan.classify(soft)[0] == "soft"
    # No status code: fall back to keyword heuristics, defaulting to soft.
    assert bouncescan.classify(b"the account has been disabled")[0] == "hard"
    assert bouncescan.classify(b"temporary glitch, try later")[0] == "soft"
    assert bouncescan.classify(b"Feedback-Type: abuse")[0] == "complaint"


def test_bounce_parses_listmonk_headers_from_attached_original():
    """A DSN nests the original message, so the X-Listmonk-* headers are not on
    the outer envelope — the parser must still find them."""
    from app import bouncescan

    dsn = (
        b"From: MAILER-DAEMON@mail.example.com\r\n"
        b"Subject: Undelivered Mail Returned to Sender\r\n"
        b"Content-Type: multipart/report; report-type=delivery-status;"
        b' boundary="XYZ"\r\n\r\n'
        b"--XYZ\r\nContent-Type: text/plain\r\n\r\nDelivery failed.\r\n"
        b"--XYZ\r\nContent-Type: message/delivery-status\r\n\r\n"
        b"Final-Recipient: rfc822; gone@test.local\r\n"
        b"Status: 5.1.1\r\n"
        b"--XYZ\r\nContent-Type: message/rfc822\r\n\r\n"
        b"X-Listmonk-Campaign: aaaaaaaa-1111-1111-1111-111111111111\r\n"
        b"X-Listmonk-Subscriber: bbbbbbbb-2222-2222-2222-222222222222\r\n"
        b"Subject: Original campaign\r\n\r\nbody\r\n"
        b"--XYZ--\r\n"
    )
    out = bouncescan.parse_message(dsn)
    assert out is not None
    assert out["email"] == "gone@test.local"
    assert out["camp_uuid"] == "aaaaaaaa-1111-1111-1111-111111111111"
    assert out["sub_uuid"] == "bbbbbbbb-2222-2222-2222-222222222222"
    assert out["btype"] == "hard"

    # Nothing to attribute the bounce to -> skipped rather than mis-recorded.
    assert bouncescan.parse_message(b"Subject: junk\r\n\r\nnothing here") is None


def test_altcha_roundtrip_and_replay_rejection():
    import base64
    import hashlib
    import json

    from app import captcha

    settings.cache["security.captcha"] = {
        "altcha": {"enabled": True, "complexity": 500},
        "hcaptcha": {"enabled": False},
    }
    ch = captcha.generate_challenge()

    for n in range(ch["maxnumber"] + 1):
        if hashlib.sha256(f"{ch['salt']}{n}".encode()).hexdigest() == ch["challenge"]:
            break
    else:
        raise AssertionError("challenge was not solvable")

    payload = base64.b64encode(
        json.dumps(
            {
                "algorithm": "SHA-256",
                "challenge": ch["challenge"],
                "number": n,
                "salt": ch["salt"],
                "signature": ch["signature"],
            }
        ).encode()
    ).decode()

    assert captcha._verify_altcha(payload) is True
    # A solution is single-use.
    assert captcha._verify_altcha(payload) is False
    # A forged signature must not pass.
    bad = base64.b64encode(
        json.dumps(
            {
                "algorithm": "SHA-256",
                "challenge": ch["challenge"],
                "number": n,
                "salt": ch["salt"],
                "signature": "0" * 64,
            }
        ).encode()
    ).decode()
    assert captcha._verify_altcha(bad) is False


def test_tmptokens_expiry_and_single_use():
    from app import tmptokens

    tmptokens.set("k", 60, "value")
    assert tmptokens.get("k") == "value"      # non-consuming
    assert tmptokens.pop("k") == "value"      # consuming
    assert tmptokens.pop("k") is None

    tmptokens.set("expired", -1, "v")
    assert tmptokens.get("expired") is None

    # Rate limit: dropped after MAX_TRIES checks.
    tmptokens.set("rl", 60, "v")
    for _ in range(tmptokens.MAX_TRIES):
        assert tmptokens.get("rl") == "v"
    assert tmptokens.get("rl") is None


def test_tx_validation_rules():
    from app.routers.tx import TxPayload, _validate

    settings.cache["smtp"] = [{"enabled": True, "host": "h", "name": ""}]

    # default mode needs exactly one of emails / ids
    for bad in (
        {"template_id": 1},
        {"template_id": 1, "subscriber_emails": ["a@b.c"], "subscriber_ids": [1]},
        {"template_id": 1, "subscriber_emails": ["a@b.c"], "subscriber_email": "d@e.f"},
        {"template_id": 1, "subscriber_mode": "external"},          # needs emails
        {"template_id": 1, "subscriber_mode": "external", "subscriber_ids": [1]},
        {"template_id": 1, "subscriber_mode": "nonsense", "subscriber_emails": ["a@b.c"]},
    ):
        try:
            _validate(TxPayload(**bad))
            raise AssertionError(f"should have been rejected: {bad}")
        except Exception as e:
            assert "400" in str(type(e)) or hasattr(e, "status_code"), e

    ok_ = _validate(TxPayload(template_id=1, subscriber_email="A@B.c"))
    assert ok_.subscriber_emails == ["a@b.c"]  # normalised


if __name__ == "__main__":
    for fn in (
        test_niladic_template_funcs_render_values,
        test_smtp_block_selection,
        test_optin_route_is_matched_before_the_two_uuid_route,
        test_tracking_pixel_always_returns_an_image,
        test_list_unsubscribe_header_is_not_encoded,
        test_campaign_headers_carry_bounce_correlation_ids,
        test_bounce_classification,
        test_bounce_parses_listmonk_headers_from_attached_original,
        test_altcha_roundtrip_and_replay_rejection,
        test_tmptokens_expiry_and_single_use,
        test_tx_validation_rules,
    ):
        fn()
        print(f"  ok  {fn.__name__}")
    print("MANAGER OK")

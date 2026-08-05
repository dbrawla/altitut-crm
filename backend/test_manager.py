"""No-DB checks for the send engine and the template call convention.

Run from backend/:  python test_manager.py   (or pytest test_manager.py)

These cover the three bugs that made sent campaigns wrong and are cheap to
regress: Go-style niladic template funcs, SMTP block selection, and the
route ordering that /subscription/optin/<uuid> depends on.
"""

import aiosmtplib
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


def test_smtp_test_unmasks_the_saved_password():
    """GET /api/settings masks secrets, so the block the settings page posts back
    to /api/settings/smtp/test carries `••••` instead of the password. Without
    un-masking, every test against an already-saved server 535s."""
    uuid = "33333333-3333-3333-3333-333333333333"
    settings.cache["smtp"] = [
        {"uuid": uuid, "enabled": True, "host": "smtp.example.com", "password": "s3cret"},
    ]

    sent: dict[str, object] = {}

    async def fake_deliver(msg, block):
        sent.update(block)

    real_deliver, manager._deliver = manager._deliver, fake_deliver
    try:
        masked = settings.masked({"smtp": settings.cache["smtp"]})["smtp"][0]
        assert masked["password"] == "•" * len("s3cret"), "precondition: it is masked"

        import asyncio

        asyncio.run(manager.send_smtp_test(dict(masked), "to@example.com"))
    finally:
        manager._deliver = real_deliver

    assert sent["password"] == "s3cret", f"mask reached SMTP: {sent['password']!r}"


def test_smtp_connections_are_reused_across_messages():
    """Every message used to pay a fresh TCP+TLS handshake and AUTH. For a
    10k-subscriber campaign that is 10k connections, which providers throttle."""
    import asyncio

    from app import manager

    connects = 0
    sent = 0

    class FakeSMTP:
        def __init__(self, **kwargs):
            self.is_connected = False

        async def connect(self):
            nonlocal connects
            connects += 1
            self.is_connected = True

        async def sendmail(self, sender, recipients, raw):
            nonlocal sent
            assert self.is_connected, "sent on a closed connection"
            sent += 1

        async def quit(self):
            self.is_connected = False

        def close(self):
            self.is_connected = False

    block = {
        "host": "smtp.example.com", "port": 587, "tls_type": "STARTTLS",
        "auth_protocol": "plain", "username": "u", "password": "p",
        "max_conns": 2, "idle_timeout": "15s", "max_msg_retries": 0,
    }

    real_smtp, aiosmtplib.SMTP = aiosmtplib.SMTP, FakeSMTP
    real_pool, manager._pool = manager._pool, manager._SmtpPool()
    try:
        async def run():
            msg = manager._build("a@b.c", "s", "<p>hi</p>", "hi", "from@x.y")
            for _ in range(6):
                await manager._deliver(msg, block)
        asyncio.run(run())
    finally:
        aiosmtplib.SMTP = real_smtp
        manager._pool = real_pool

    assert sent == 6, sent
    # Serially, one pooled connection carries all six messages.
    assert connects == 1, f"expected connection reuse, opened {connects}"


def test_smtp_pool_discards_a_connection_that_errored():
    """A connection whose protocol state is unknown must not be handed back."""
    import asyncio

    from app import manager

    connects = 0

    class FlakySMTP:
        def __init__(self, **kwargs):
            self.is_connected = False

        async def connect(self):
            nonlocal connects
            connects += 1
            self.is_connected = True

        async def sendmail(self, sender, recipients, raw):
            raise OSError("connection reset")

        async def quit(self):
            self.is_connected = False

        def close(self):
            self.is_connected = False

    block = {"host": "h", "port": 25, "max_conns": 1, "max_msg_retries": 1}

    real_smtp, aiosmtplib.SMTP = aiosmtplib.SMTP, FlakySMTP
    real_pool, manager._pool = manager._pool, manager._SmtpPool()
    try:
        async def run():
            msg = manager._build("a@b.c", "s", "<p>hi</p>", "hi", "from@x.y")
            try:
                await manager._deliver(msg, block)
            except OSError:
                pass
        asyncio.run(run())
    finally:
        aiosmtplib.SMTP = real_smtp
        manager._pool = real_pool

    # 1 initial + 1 retry, each a fresh connection rather than the poisoned one.
    assert connects == 2, f"broken connection was reused: {connects} connects"


def test_duration_parsing_for_pool_timeouts():
    from app.manager import _duration_seconds

    assert _duration_seconds("15s", 0) == 15.0
    assert _duration_seconds("10ms", 0) == 0.01
    assert _duration_seconds("2m", 0) == 120.0
    assert _duration_seconds("", 9) == 9.0
    assert _duration_seconds("nonsense", 9) == 9.0
    assert _duration_seconds(30, 0) == 30.0


def test_sql_segmentation_blocks_statement_breakout():
    """subscribers:sql_query is meant to grant filtering, not arbitrary
    statement execution. The condition is interpolated into a WHERE clause, so
    `;` and comment markers would let a caller append their own statement."""
    from app.routers.subscribers import _query_cond

    # role id 2 = not the super admin, so has_perm() consults the permission list
    admin = {"id": 1, "user_role": {"id": 2, "permissions": ["subscribers:sql_query"]}}

    # Plain conditions still pass through.
    assert _query_cond(admin, "subscribers.status = 'enabled'") == (
        "(subscribers.status = 'enabled')"
    )
    assert _query_cond(admin, "") == "TRUE"

    for bad in (
        "1=1; DROP TABLE subscribers",
        "1=1 -- comment",
        "1=1 /* block */",
        "1=1) OR (TRUE",  # unbalanced: closes the wrapper early
    ):
        try:
            _query_cond(admin, bad)
        except Exception as e:
            assert getattr(e, "status_code", None) == 400, (bad, e)
        else:
            raise AssertionError(f"should have been rejected: {bad}")

    # Without the permission it is refused outright.
    try:
        _query_cond({"id": 2, "user_role": {"id": 2, "permissions": []}}, "1=1")
    except Exception as e:
        assert getattr(e, "status_code", None) == 400, e
    else:
        raise AssertionError("missing permission should be rejected")


def test_import_detects_email_and_name_columns():
    """CSVs exported from other tools rarely use listmonk's own header names."""
    import csv as _csv
    import io as _io

    from app.importer import _row_name, map_columns

    def parse(text):
        r = _csv.DictReader(_io.StringIO(text))
        rows = list(r)
        return [h for h in (r.fieldnames or []) if h], rows

    # First/last pair, arbitrary casing and separators.
    headers, rows = parse("First_Name,Last Name,E-Mail Address\nAda,Lovelace,ada@x.io\n")
    cols = map_columns(headers, rows)
    assert cols["email"] == "E-Mail Address", cols
    assert cols["first"] == "First_Name" and cols["last"] == "Last Name", cols
    # Joined with a space so tmpl.py's FirstName/LastName split works.
    assert _row_name(rows[0], cols) == "Ada Lovelace"

    # A single full-name column.
    headers, rows = parse("Full Name,email\nGrace Hopper,grace@x.io\n")
    cols = map_columns(headers, rows)
    assert cols["name"] == "Full Name" and cols["first"] is None, cols
    assert _row_name(rows[0], cols) == "Grace Hopper"

    # First name only.
    headers, rows = parse("fname,email\nAlan,alan@x.io\n")
    cols = map_columns(headers, rows)
    assert _row_name(rows[0], cols) == "Alan"

    # listmonk's own format still works.
    headers, rows = parse("email,name,attributes\na@b.c,A B,{}\n")
    cols = map_columns(headers, rows)
    assert cols["email"] == "email" and cols["name"] == "name"
    assert cols["attribs"] == "attributes"

    # No recognisable email header — fall back to sniffing the values.
    headers, rows = parse("col1,col2,col3\nAda,Lovelace,ada@x.io\n")
    cols = map_columns(headers, rows)
    assert cols["email"] == "col3", cols

    # Nothing that looks like an address at all.
    headers, rows = parse("a,b\n1,2\n")
    assert map_columns(headers, rows)["email"] is None

    # `name` must not be claimed when it is really the first-name column.
    headers, rows = parse("Name,Surname,Email\nKatherine,Johnson,kj@x.io\n")
    cols = map_columns(headers, rows)
    assert cols["last"] == "Surname"
    assert _row_name(rows[0], cols) == "Katherine Johnson", cols


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
        test_smtp_test_unmasks_the_saved_password,
        test_smtp_connections_are_reused_across_messages,
        test_smtp_pool_discards_a_connection_that_errored,
        test_duration_parsing_for_pool_timeouts,
        test_sql_segmentation_blocks_statement_breakout,
        test_import_detects_email_and_name_columns,
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

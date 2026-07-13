"""No-DB smoke test: app imports, routes resolve, static assets serve.

Run from backend/:  python test_smoke.py   (or pytest test_smoke.py)
DB-backed endpoints need Postgres and are exercised by running the app itself.
"""

from starlette.testclient import TestClient

import app.main as m

# ponytail: TestClient without a context manager skips lifespan (no DB needed).
client = TestClient(m.app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"data": True}


def test_i18n():
    r = client.get("/api/lang/en")
    assert r.status_code == 200 and r.json()["data"]["_.code"] == "en"
    assert client.get("/api/lang/nope").status_code == 404


def test_spa_fallback():
    r = client.get("/admin/subscribers")  # deep link -> index.html
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert client.get("/api/no-such-endpoint").status_code == 404  # stays JSON 404


def test_auth_required():
    assert client.get("/api/settings").status_code == 401


if __name__ == "__main__":
    for fn in (test_health, test_i18n, test_spa_fallback, test_auth_required):
        fn()
    print("SMOKE OK")

"""Firestore client — lazy singleton, only initialized when a domain's repo
backend is actually set to "firestore" (app/config.py's repo_backend_* flags).
"""

from __future__ import annotations

from google.cloud.firestore import Client

from app.config import env

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred = credentials.Certificate(env.firebase_credentials_path)
            firebase_admin.initialize_app(cred)
        from firebase_admin import firestore

        _client = firestore.client()
    return _client

"""Password hashing — moved off Postgres's pgcrypto (CRYPT/GEN_SALT('bf'))
to Python bcrypt directly. Pure win independent of the Firestore migration:
removes a DB-engine dependency, makes hashing testable without a live DB.

Existing hashes stay valid: pgcrypto's GEN_SALT('bf') produces standard
`$2a$` bcrypt strings, which Python's bcrypt verifies unchanged - this is a
transparent swap, not a rehash-on-migrate.
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # Malformed/foreign hash format - never let it crash the login path.
        return False

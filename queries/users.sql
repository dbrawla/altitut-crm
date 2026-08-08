-- name: create-user
-- $3 is the final value to store: a bcrypt hash (app/passwords.py), a raw
-- API token, or '' - hashing/token generation happens in Python now, not
-- via pgcrypto's CRYPT()/GEN_SALT('bf'). $7/$8 (role IDs) are stored as-is,
-- unvalidated - app/repos/users.py validates against role_repo instead of
-- a same-database FK subquery, since Roles may live in Firestore now.
INSERT INTO users (username, password_login, password, email, name, type, user_role_id, list_role_id, status)
    VALUES($1, $2, (CASE WHEN $3 = '' THEN NULL ELSE $3 END), $4, $5, $6, $7, $8, $9) RETURNING id;

-- name: update-user
-- The "don't demote/disable the last superadmin" guard moved to Python
-- (app/repos/users.py) - it needs to count OTHER enabled superadmins via
-- role_repo now, which a same-database SQL subquery can't do once Roles
-- may live in Firestore. This unconditionally applies the given fields;
-- callers only invoke it after the guard passes.
UPDATE users SET
    username=(CASE WHEN $2 != '' THEN $2 ELSE username END),
    password_login=$3,
    -- $4 is a bcrypt hash (already hashed in Python) or '' to leave unchanged.
    password=(
        CASE
            WHEN users.type = 'api' AND ($7 = '' OR $7 = 'api') THEN password
            WHEN $3 = TRUE THEN (CASE WHEN $4 != '' THEN $4 ELSE password END)
            ELSE NULL
        END
    ),
    email=(CASE WHEN $5 != '' THEN $5 ELSE email END),
    name=(CASE WHEN $6 != '' THEN $6 ELSE name END),
    type=(CASE WHEN $7 != '' THEN $7::user_type ELSE type END),
    user_role_id=(CASE WHEN $8 != 0 THEN $8 ELSE user_role_id END),
    list_role_id=(
        CASE
            WHEN $9 < 0 THEN NULL
            WHEN $9 > 0 THEN $9
            ELSE list_role_id END
    ),
    status=(CASE WHEN $10 != '' THEN $10::user_status ELSE status END),
    updated_at=NOW()
    WHERE id=$1;

-- name: delete-users
-- The "leave at least one enabled superadmin" guard moved to Python for the
-- same reason as update-user above.
DELETE FROM users WHERE id = ANY($1);

-- name: get-users
SELECT * FROM users ORDER BY created_at;

-- name: get-user
SELECT * FROM users
    WHERE
    (
        CASE
            WHEN $1::INT != 0 THEN id = $1
            WHEN $2::TEXT != '' THEN username = $2
            WHEN $3::TEXT != '' THEN email = $3
        END
    );

-- name: count-other-enabled-superadmins
SELECT COUNT(*) FROM users
    WHERE NOT(id = ANY($1)) AND user_role_id = 1 AND type = 'user' AND status = 'enabled';


-- name: get-api-tokens
SELECT username, password FROM users WHERE status='enabled' AND type='api';

-- name: get-user-for-login
-- Fetches the candidate row by username only - password verification
-- happens in Python (app/passwords.py) against the returned hash, since
-- bcrypt comparison can't be expressed as a SQL predicate anymore.
SELECT users.*, r.name as role_name, r.permissions FROM users
LEFT JOIN roles r ON (r.id = users.user_role_id)
WHERE username = $1 AND status != 'disabled' AND password_login = TRUE;

-- name: update-user-profile
-- $5 is a bcrypt hash (already hashed in Python) or '' to leave unchanged.
UPDATE users SET name=$2, email=(CASE WHEN password_login THEN $3 ELSE email END),
    password=(CASE WHEN $4 = TRUE THEN (CASE WHEN $5 != '' THEN $5 ELSE password END) ELSE NULL END)
    WHERE id=$1;

-- name: update-user-login
UPDATE users SET loggedin_at=NOW(), avatar=(CASE WHEN $2 != '' THEN $2 ELSE avatar END) WHERE id=$1;

-- name: set-user-twofa
UPDATE users SET twofa_type=$2::twofa_type, twofa_key=$3, updated_at=NOW() WHERE id=$1;

-- name: delete-user-sessions
DELETE FROM sessions WHERE data->>'user_id' = $1 AND ($2 = '' OR id != $2);

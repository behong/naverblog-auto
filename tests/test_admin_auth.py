import admin_auth


def test_password_hash_verifies_without_retaining_plaintext(monkeypatch):
    password_hash = admin_auth.create_password_hash("correct-horse-battery-staple")
    monkeypatch.setattr(admin_auth, "_ADMIN_PASSWORD_HASH", password_hash)

    assert admin_auth.configured() is True
    assert admin_auth.verify_password("correct-horse-battery-staple") is True
    assert admin_auth.verify_password("incorrect-password") is False


def test_admin_session_is_opaque_and_requires_matching_csrf(monkeypatch):
    admin_auth._sessions.clear()
    monkeypatch.setattr(admin_auth, "_SESSION_TTL_SECONDS", 600)

    raw_token, session = admin_auth.create_session()

    assert raw_token not in admin_auth._sessions
    assert admin_auth.session_for(raw_token) == session
    assert admin_auth.csrf_valid(session, session.csrf_token) is True
    assert admin_auth.csrf_valid(session, "wrong-token") is False

    admin_auth.revoke_session(raw_token)
    assert admin_auth.session_for(raw_token) is None


def test_short_password_is_rejected_when_creating_hash():
    try:
        admin_auth.create_password_hash("too-short")
    except ValueError as exc:
        assert "12자" in str(exc)
    else:
        raise AssertionError("short password should be rejected")

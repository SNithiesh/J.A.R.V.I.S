"""
Phase 3 unit tests — auth is where silent bugs become open doors,
so these are written like an attacker, not like a demo.
Run: pytest backend/tests -q
"""
import datetime

import pytest

from app import auth


def test_token_roundtrip():
    tok = auth.make_token("pratap", "access", datetime.timedelta(minutes=5))
    assert auth.decode_token(tok, "access") == "pratap"


def test_refresh_token_cannot_act_as_access_token():
    # The 30-day pass must never open doors only the 30-minute badge opens.
    refresh = auth.make_token("pratap", "refresh", datetime.timedelta(days=30))
    with pytest.raises(ValueError):
        auth.decode_token(refresh, "access")


def test_expired_token_is_rejected():
    expired = auth.make_token("pratap", "access", datetime.timedelta(minutes=-1))
    with pytest.raises(ValueError):
        auth.decode_token(expired, "access")


def test_tampered_token_is_rejected():
    tok = auth.make_token("pratap", "access", datetime.timedelta(minutes=5))
    tampered = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
    with pytest.raises(ValueError):
        auth.decode_token(tampered, "access")


def test_garbage_token_is_rejected():
    with pytest.raises(ValueError):
        auth.decode_token("not.a.jwt", "access")


def test_password_hash_verifies_and_never_stores_plaintext():
    hashed = auth.hash_password("correct horse battery staple")
    assert "correct" not in hashed                      # one-way scramble
    assert auth.verify_password("correct horse battery staple", hashed)
    assert not auth.verify_password("wrong password", hashed)


def test_two_hashes_of_same_password_differ():
    # bcrypt salts every hash — identical passwords produce different
    # hashes, so a leaked database can't be cracked with one lookup table.
    a = auth.hash_password("same-password")
    b = auth.hash_password("same-password")
    assert a != b
    assert auth.verify_password("same-password", a)
    assert auth.verify_password("same-password", b)

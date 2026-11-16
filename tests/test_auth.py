from api import auth


def test_password_round_trip():
    stored = auth.hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    assert "correct horse" not in stored
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("wrong password", stored)


def test_same_password_hashes_differently_each_time():
    assert auth.hash_password("same-password") != auth.hash_password("same-password")


def test_garbage_hash_is_rejected_not_crashed_on():
    for stored in ("", "plain", "scrypt$1$2", "md5$a$b$c$d$e", "scrypt$x$8$1$AAAA$AAAA"):
        assert not auth.verify_password("anything", stored)


def test_session_token_round_trip():
    token = auth.create_session_token(7, "secret-a-that-is-long-enough-for-hs256", hours=1)
    assert auth.read_session_token(token, "secret-a-that-is-long-enough-for-hs256") == 7


def test_token_signed_with_another_key_is_refused():
    token = auth.create_session_token(7, "secret-a-that-is-long-enough-for-hs256", hours=1)
    assert auth.read_session_token(token, "secret-b-that-is-long-enough-for-hs256") is None


def test_expired_token_is_refused():
    token = auth.create_session_token(7, "secret-a-that-is-long-enough-for-hs256", hours=-1)
    assert auth.read_session_token(token, "secret-a-that-is-long-enough-for-hs256") is None


def test_tampered_token_is_refused():
    token = auth.create_session_token(7, "secret-a-that-is-long-enough-for-hs256", hours=1)
    assert auth.read_session_token(token[:-2] + "xx", "secret-a-that-is-long-enough-for-hs256") is None
    assert auth.read_session_token("not-a-token", "secret-a-that-is-long-enough-for-hs256") is None


def test_secret_is_generated_once_and_kept_private(tmp_path):
    path = tmp_path / "secret.key"
    first = auth.load_or_create_secret("", path)
    assert len(first) >= 40
    assert auth.load_or_create_secret("", path) == first
    assert path.stat().st_mode & 0o077 == 0  # nobody else can read it
    assert auth.load_or_create_secret("from-env", path) == "from-env"


def test_limiter_locks_after_repeated_failures_then_unlocks():
    now = [0.0]
    limiter = auth.LoginLimiter(max_failures=3, lock_seconds=60, clock=lambda: now[0])
    for _ in range(2):
        limiter.record_failure("ali", "1.2.3.4")
    assert limiter.seconds_locked("ali", "1.2.3.4") == 0
    limiter.record_failure("ALI", "1.2.3.4")  # usernames are not case-sensitive
    assert limiter.seconds_locked("ali", "1.2.3.4") == 60
    assert limiter.seconds_locked("ali", "9.9.9.9") == 0  # another address is unaffected
    assert limiter.seconds_locked("sara", "1.2.3.4") == 0
    now[0] = 61
    assert limiter.seconds_locked("ali", "1.2.3.4") == 0


def test_limiter_resets_on_success():
    limiter = auth.LoginLimiter(max_failures=3)
    limiter.record_failure("ali", "x")
    limiter.record_failure("ali", "x")
    limiter.record_success("ali", "x")
    limiter.record_failure("ali", "x")
    assert limiter.seconds_locked("ali", "x") == 0

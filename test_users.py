import pytest

from clarity.core import users


def test_accounts_authenticate_and_keep_sessions_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "DATABASE_FILE", tmp_path / "clarity.sqlite3")
    monkeypatch.setattr(users, "PASSWORD_ROUNDS", 1_000)

    alice = users.register_user("alice@example.com", "password-1", "Alice")
    bob = users.register_user("bob@example.com", "password-2", "Bob")

    assert alice["user"]["id"] != bob["user"]["id"]
    assert users.user_for_token(alice["token"])["email"] == "alice@example.com"
    assert users.login_user("alice@example.com", "password-1")["user"]["display_name"] == "Alice"
    with pytest.raises(ValueError, match="邮箱或密码错误"):
        users.login_user("alice@example.com", "wrong-password")

    users.logout_user(alice["token"])
    assert users.user_for_token(alice["token"]) is None
    assert users.user_for_token(bob["token"])["email"] == "bob@example.com"

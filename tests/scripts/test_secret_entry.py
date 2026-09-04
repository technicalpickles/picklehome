import os

import pytest
from dotenv import dotenv_values

from scripts.secret_entry import upsert_env_vars


def test_creates_file_when_missing(tmp_path):
    env = tmp_path / ".env"
    upsert_env_vars(env, {"FLO_USERNAME": "a@b.com"})
    assert env.read_text() == 'FLO_USERNAME="a@b.com"\n'


def test_replaces_existing_key_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="1"\nFLO_USERNAME="old"\nB="2"\n')
    upsert_env_vars(env, {"FLO_USERNAME": "new"})
    assert env.read_text() == 'A="1"\nFLO_USERNAME="new"\nB="2"\n'


def test_appends_new_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="1"\n')
    upsert_env_vars(env, {"FLO_PASSWORD": "hunter2"})
    assert env.read_text() == 'A="1"\nFLO_PASSWORD="hunter2"\n'


def test_preserves_comments_and_blank_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nA="1"\n')
    upsert_env_vars(env, {"B": "2"})
    assert env.read_text() == '# a comment\n\nA="1"\nB="2"\n'


def test_does_not_match_key_as_substring(tmp_path):
    env = tmp_path / ".env"
    env.write_text('MY_FLO_USERNAME="untouched"\n')
    upsert_env_vars(env, {"FLO_USERNAME": "new"})
    assert env.read_text() == 'MY_FLO_USERNAME="untouched"\nFLO_USERNAME="new"\n'


def test_quotes_and_escapes_special_characters(tmp_path):
    env = tmp_path / ".env"
    upsert_env_vars(env, {"P": 'a b"c\\d#e'})
    assert env.read_text() == 'P="a b\\"c\\\\d#e"\n'


def test_appends_trailing_newline_when_file_lacks_one(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="1"')
    upsert_env_vars(env, {"B": "2"})
    assert env.read_text() == 'A="1"\nB="2"\n'


def test_sets_owner_only_permissions(tmp_path):
    env = tmp_path / ".env"
    upsert_env_vars(env, {"A": "1"})
    assert env.stat().st_mode & 0o777 == 0o600


def test_rejects_invalid_key_name(tmp_path):
    with pytest.raises(ValueError, match="not a valid env var name"):
        upsert_env_vars(tmp_path / ".env", {"bad key": "1"})


def test_rejects_values_with_dollar_brace_interpolation(tmp_path):
    """python-dotenv interpolates ${{...}} regardless of quoting."""
    with pytest.raises(ValueError, match="contains '\\$\\{...\\}' which python-dotenv interpolates"):
        upsert_env_vars(tmp_path / ".env", {"TOKEN": "tok${HOME}en"})
    # Verify file was not written
    assert not (tmp_path / ".env").exists()


def test_replaces_all_occurrences_of_duplicate_key(tmp_path):
    """python-dotenv uses the last occurrence; we must replace all."""
    env = tmp_path / ".env"
    env.write_text('FLO_USERNAME="first"\nA="1"\nFLO_USERNAME="second"\n')
    upsert_env_vars(env, {"FLO_USERNAME": "new"})
    # Both lines should be replaced, preventing the stale one from being used
    assert env.read_text() == 'FLO_USERNAME="new"\nA="1"\nFLO_USERNAME="new"\n'
    # Verify round-trip: only the last occurrence matters to dotenv
    assert dotenv_values(env)["FLO_USERNAME"] == "new"


def test_preserves_export_prefix(tmp_path):
    """Handle lines like `export KEY=value`."""
    env = tmp_path / ".env"
    env.write_text('export FLO_USERNAME="old"\n')
    upsert_env_vars(env, {"FLO_USERNAME": "new"})
    assert env.read_text() == 'export FLO_USERNAME="new"\n'


def test_rejects_values_with_literal_newline(tmp_path):
    """Newlines corrupt file structure on the next write."""
    with pytest.raises(ValueError, match="contains a literal newline"):
        upsert_env_vars(tmp_path / ".env", {"A": "line1\nline2"})
    # Verify file was not written
    assert not (tmp_path / ".env").exists()


def test_rejects_values_with_carriage_return(tmp_path):
    """Path.read_text() uses universal newlines, so a lone \\r round-trips to
    \\n on the next read and corrupts the file the same way an unescaped \\n
    would -- must be rejected too, not just \\n."""
    with pytest.raises(ValueError, match="contains a literal newline"):
        upsert_env_vars(tmp_path / ".env", {"A": "line1\rline2"})
    assert not (tmp_path / ".env").exists()


def test_no_leftover_temp_file_after_a_successful_write(tmp_path):
    """The atomic write goes through a sibling temp file; it must not survive."""
    env = tmp_path / ".env"
    upsert_env_vars(env, {"A": "1"})
    leftovers = [p for p in tmp_path.iterdir() if p != env]
    assert leftovers == []


def test_replace_step_is_atomic_not_truncate_in_place(tmp_path, monkeypatch):
    """Simulate a crash between opening the temp file and the atomic
    replace: the original .env must be left completely untouched, not
    truncated. This is the failure mode the temp-file+os.replace() rewrite
    exists to prevent (previously O_TRUNC opened the real file in place)."""
    env = tmp_path / ".env"
    env.write_text('FLO_USERNAME="old"\n')

    real_replace = os.replace

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(RuntimeError, match="simulated crash"):
        upsert_env_vars(env, {"FLO_USERNAME": "new"})

    monkeypatch.setattr(os, "replace", real_replace)

    # Original file untouched -- not truncated, not partially written.
    assert env.read_text() == 'FLO_USERNAME="old"\n'
    # No leftover temp file.
    leftovers = [p for p in tmp_path.iterdir() if p != env]
    assert leftovers == []


def test_new_file_created_with_0600_permissions(tmp_path):
    """File should not have a window where it's readable by others."""
    env = tmp_path / ".env"
    upsert_env_vars(env, {"A": "secret"})
    # Use stat to verify permissions were set correctly
    mode = env.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_round_trip_through_dotenv_consumer(tmp_path):
    """Verify written values are readable by python-dotenv without corruption."""
    env = tmp_path / ".env"
    # Adversarial but legal password: quote, backslash, hash, space, equals
    password = 'my"pass\\word#key=value test'
    upsert_env_vars(env, {"SECRET": password})

    # Read back using dotenv (the real consumer)
    values = dotenv_values(env)
    assert values["SECRET"] == password, f"Round-trip failed: {values['SECRET']!r} != {password!r}"


def test_appends_multiple_new_keys_in_order(tmp_path):
    """Multiple newly-appended keys must preserve insertion order."""
    env = tmp_path / ".env"
    # Python 3.7+ dicts preserve insertion order; call with three new keys
    upsert_env_vars(env, {"FLO_USERNAME": "user1", "FLO_PASSWORD": "pass1", "FLO_TOKEN": "token1"})
    assert env.read_text() == 'FLO_USERNAME="user1"\nFLO_PASSWORD="pass1"\nFLO_TOKEN="token1"\n'

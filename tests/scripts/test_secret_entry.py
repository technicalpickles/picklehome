import pytest

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

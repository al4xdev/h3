import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('migration', Path(__file__).parents[1] / 'tools/migrate_grok_prompts.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_explicit_migration_preserves_sequential_and_later_customization(tmp_path):
    root = tmp_path / 'data'
    (root / 'grok').mkdir(parents=True)
    (root / 'roteiros').mkdir()
    sequential = b'{"model":"fixed", "system_prompt":" exact\\n text "}\n'
    old = b'{"system_prompt":"old sequential prose","model":"fixed"}'
    (root / 'grok/editor.json').write_bytes(sequential)
    story = root / 'roteiros/editor.json'
    story.write_bytes(old)
    sha = lambda value: hashlib.sha256(value).hexdigest()
    args = (root, tmp_path / 'snapshot', sha(old), sha(sequential))
    assert migration.migrate(*args)
    assert (root / 'grok/editor.json').read_bytes() == sequential
    assert (tmp_path / 'snapshot/story-editor.json').read_bytes() == old
    assert json.loads(story.read_bytes())['model'] == 'fixed'
    assert not migration.migrate(*args)
    custom = b'{"system_prompt":"owner customization"}'
    story.write_bytes(custom)
    with pytest.raises(ValueError, match='custom instructions preserved'):
        migration.migrate(*args)
    assert story.read_bytes() == custom


def test_changed_sequential_stops_before_any_snapshot(tmp_path):
    root = tmp_path / 'data'
    (root / 'grok').mkdir(parents=True)
    (root / 'roteiros').mkdir()
    (root / 'grok/editor.json').write_text('{}')
    (root / 'roteiros/editor.json').write_text('{}')
    with pytest.raises(ValueError, match='Sequential config changed'):
        migration.migrate(root, tmp_path / 'snapshot', 'wrong', 'wrong')
    assert not (tmp_path / 'snapshot').exists()


@pytest.mark.parametrize('kind', ['source-link', 'parent-link', 'hardlink', 'oversize'])
def test_unsafe_config_paths_and_files_are_rejected(tmp_path, kind):
    root = tmp_path / 'data'
    (root / 'grok').mkdir(parents=True)
    (root / 'roteiros').mkdir()
    sequential = root / 'grok/editor.json'
    story = root / 'roteiros/editor.json'
    sequential.write_bytes(b'{}')
    story.write_bytes(b'{}')
    if kind == 'source-link':
        story.rename(root / 'saved.json')
        story.symlink_to(root / 'saved.json')
    elif kind == 'parent-link':
        (root / 'roteiros').rename(root / 'saved')
        (root / 'roteiros').symlink_to(root / 'saved', target_is_directory=True)
    elif kind == 'hardlink':
        import os
        os.link(story, root / 'linked.json')
    else:
        story.write_bytes(b'x' * (migration.MAX_BYTES + 1))
    with pytest.raises((ValueError, OSError)):
        migration.migrate(root, tmp_path / 'snapshot', 'wrong', 'wrong')
    assert not (tmp_path / 'snapshot').exists()


def test_foreign_owner_is_rejected(tmp_path, monkeypatch):
    import os
    target = tmp_path / 'editor.json'
    target.write_bytes(b'{}')
    with migration._directory(tmp_path, ()) as directory:
        monkeypatch.setattr(migration.os, 'getuid', lambda: os.stat(target).st_uid + 1)
        with pytest.raises(ValueError, match='owned single-link'):
            migration.read_config(directory)


def test_private_snapshot_and_race_before_publish(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    (root / 'grok').mkdir(parents=True)
    (root / 'roteiros').mkdir()
    sequential = root / 'grok/editor.json'
    story = root / 'roteiros/editor.json'
    sequential.write_bytes(b'{}')
    story.write_bytes(b'{"system_prompt":"old"}')
    sha = lambda value: hashlib.sha256(value).hexdigest()
    hashes = sha(story.read_bytes()), sha(sequential.read_bytes())
    original = migration.write_private

    def race(directory, name, value):
        original(directory, name, value)
        if name.startswith('.editor-migration-'):
            story.write_bytes(b'{"system_prompt":"concurrent owner edit"}')

    monkeypatch.setattr(migration, 'write_private', race)
    snapshot = tmp_path / 'snapshot'
    with pytest.raises(ValueError, match='changed during migration'):
        migration.migrate(root, snapshot, *hashes)
    assert story.read_bytes() == b'{"system_prompt":"concurrent owner edit"}'
    assert snapshot.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in snapshot.iterdir())
    assert list(snapshot.glob('unpublished-*.json'))
    assert not list(story.parent.glob('.editor-migration-*'))


def test_complete_story_prompt_requires_english_generation_text():
    assert 'Write every blocks[].prompt in English' in migration.FULL_STORY_PROMPT
    assert 'preserving any literal dialogue explicitly requested by the user' in migration.FULL_STORY_PROMPT
    assert 'Você é' not in migration.FULL_STORY_PROMPT

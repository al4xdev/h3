import argparse
import hashlib
import json
import os
from pathlib import Path
from stat import S_ISREG
from uuid import uuid4

from h3_backend.infrastructure.grok_image import _directory
from h3_backend.roteiro import locked

FULL_STORY_PROMPT = '''You are a screenwriter for videos divided into sequential blocks. Turn the user's idea into a complete story using the supplied image as visual reference. Preserve identity, appearance, and continuity of pose, clothing, setting, and action, except for changes requested by the user. Respect the requested number of blocks and duration of each block. Plan actions that can be performed within that time and a clear transition between every pair of blocks. Do not invent instructions that contradict the idea.
Respond only with a valid JSON object, without markdown or extra text, using this format: {"name":"Short story title","blocks":[{"action":"Simple description of the block action","duration_seconds":8,"prompt":"Complete prompt for generating this block"}]}. Use exactly the requested number of objects in blocks. duration_seconds must be the requested duration for that block. action and prompt must be nonempty strings. Write every blocks[].prompt in English, preserving any literal dialogue explicitly requested by the user. The title and action descriptions may follow the user's language. Each prompt describes its block's beginning, action, and ending, and respects the final state of the previous block. Do not include IDs, seeds, paths, models, or other fields. Do not generate videos: produce only the editable story proposal.'''


MAX_BYTES = 1024 * 1024


def read_config(directory: int) -> bytes:
    fd = os.open('editor.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise ValueError('Invalid editor config: expected owned single-link regular file up to 1 MiB.')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            value = source.read(MAX_BYTES + 1)
        if len(value) > MAX_BYTES:
            raise ValueError('Editor config exceeds 1 MiB.')
        return value
    finally:
        os.close(fd)


def write_private(directory: int, name: str, value: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())


def migrate(root: Path, snapshot: Path, expected_story: str, expected_sequential: str) -> bool:
    with _directory(root, ('grok',)) as sequential, _directory(root, ('roteiros',)) as story, locked(story):
        sequential_bytes = read_config(sequential)
        story_bytes = read_config(story)
        digest = lambda value: hashlib.sha256(value).hexdigest()
        if digest(sequential_bytes) != expected_sequential:
            raise ValueError('Sequential config changed; migration stopped.')
        config = json.loads(story_bytes)
        if config.get('system_prompt') == FULL_STORY_PROMPT:
            return False
        if digest(story_bytes) != expected_story:
            raise ValueError('Story config changed; custom instructions preserved.')
        json.loads(sequential_bytes)
        with _directory(snapshot.parent, ()) as parent:
            os.mkdir(snapshot.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        with _directory(snapshot, ()) as backup:
            for name, value in [('sequential-editor.json', sequential_bytes), ('story-editor.json', story_bytes)]:
                write_private(backup, name, value)
            write_private(backup, 'sha256.json', (json.dumps({'sequential': digest(sequential_bytes), 'story': digest(story_bytes)}, indent=2) + '\n').encode())
            os.fsync(backup)
            config['system_prompt'] = FULL_STORY_PROMPT
            replacement = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode()
            temporary = f'.editor-migration-{uuid4()}'
            write_private(story, temporary, replacement)
            if read_config(story) != story_bytes or read_config(sequential) != sequential_bytes:
                os.rename(temporary, f'unpublished-{uuid4()}.json', src_dir_fd=story, dst_dir_fd=backup)
                os.fsync(backup)
                os.fsync(story)
                raise ValueError('Config changed during migration; replacement was not published.')
            os.replace(temporary, 'editor.json', src_dir_fd=story, dst_dir_fd=story)
            os.fsync(story)
            if read_config(sequential) != sequential_bytes:
                raise ValueError('Sequential config changed concurrently.')
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description='Explicit local migration of the complete-story prompt; never reads OAuth.')
    parser.add_argument('--data-root', type=Path, default=Path('.data'))
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--expected-story-sha256', required=True)
    parser.add_argument('--expected-sequential-sha256', required=True)
    args = parser.parse_args()
    changed = migrate(args.data_root, args.snapshot_dir, args.expected_story_sha256, args.expected_sequential_sha256)
    print('Complete-story prompt updated; sequential config preserved.' if changed else 'Already migrated; no files changed.')


if __name__ == '__main__':
    main()

"""The prompt editor's serialized text is passed verbatim, not rendered as HTML."""

import json
from pathlib import Path

import pytest

from h3_backend.generation.models import ContinueRequest, RunRequest
from h3_backend.generation.workflow import WorkflowBuilder

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = '''# Scene — dança suave

## References
- **Identity:** <Picture 1>
- **Motion:** <Video 1>
- **Sound:** <Audio 1>

## Action
Continue the fully clothed adult dancer's movement naturally.\x20\x20
Preserve appearance, clothing and the geometric wall.

> Keep the camera stable; no dialogue.

```text
<Picture 1> + <Video 1>
```

'''


def test_full_markdown_survives_request_workflow_and_json_serialization():
    request = RunRequest.model_validate_json(
        json.dumps({"seed": 7, "prompt": MARKDOWN}, ensure_ascii=False)
    )
    graph = WorkflowBuilder(ROOT).build(
        prompt=request.prompt,
        seed=request.seed,
        duration_seconds=request.duration_seconds,
        references=[{"type": "image", "filename": "identity.png [input]"}],
        filename_prefix="h3_backend/markdown-test/chunk",
    )
    payload = json.loads(json.dumps({"prompt": graph}, ensure_ascii=False))
    assert request.prompt == MARKDOWN
    assert payload["prompt"]["365"]["inputs"]["prompt"] == MARKDOWN
    assert payload["prompt"]["5"]["inputs"]["prompt"] == ["365", 0]


def test_continuation_preserves_markdown_including_newlines_and_tags():
    request = ContinueRequest.model_validate_json(
        json.dumps({"seed": 8, "prompt": MARKDOWN}, ensure_ascii=False)
    )
    assert request.prompt == MARKDOWN
    assert json.loads(request.model_dump_json())["prompt"] == MARKDOWN


@pytest.mark.parametrize("operation", ["i2v", "v2v"])
def test_dispatcher_preserves_literal_markdown_for_each_operation(operation):
    references = [{"type": "image", "filename": "identity.png [input]", "role": "identity"}]
    if operation == "v2v":
        references.insert(0, {
            "type": "image", "filename": "end.png [input]", "role": "initial_frame",
        })
        references.append({
            "type": "video", "filename": "tail.mp4 [input]", "role": "motion_video",
        })
    builder = WorkflowBuilder(ROOT)
    graph = builder.build(
        operation=operation, prompt=MARKDOWN, seed=8, duration_seconds=2.3,
        references=references, filename_prefix="h3_backend/markdown-test/chunk",
    )
    assert json.loads(json.dumps(graph))["365"]["inputs"]["prompt"] == MARKDOWN

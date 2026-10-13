import json
import tempfile

import httpx
import pytest
from pydantic import ValidationError
from test_grok import finished
from test_grok_multimodal import FakeManager, input_fixture

from h3_backend.grok import FIXED_EDITOR_MODEL, EditorConfig, Grok, PromptRequest, save_editor
from h3_backend.infrastructure.grok_image import BUFFER_BYTES, images_json_body
from h3_backend.infrastructure.grok_oauth import OAuthError

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"name": {"type": "string"}}, "required": ["name"],
}
FORMAT = {"format": {"type": "json_schema", "name": "h3_roteiro",
                     "strict": True, "schema": SCHEMA}}


@pytest.mark.parametrize("with_image", [False, True])
async def test_internal_structured_request_keeps_model_and_reference(tmp_path, with_image):
    seen = []
    reference = input_fixture(tmp_path)[0] if with_image else None
    save_editor(tmp_path, EditorConfig(system_prompt="sequential editor", model=FIXED_EDITOR_MODEL))

    def handler(request):
        seen.append(json.loads(request.content))
        assert int(request.headers.get("content-length")) == len(request.content)
        return httpx.Response(200, json=finished('{"name":"Scene"}'))

    grok = Grok(FakeManager(handler), "ignored", root=tmp_path)
    result = await grok.complete(PromptRequest(prompt="idea", system_prompt="script editor",
                                             reference=reference), output_schema=SCHEMA)
    assert result == {"text": '{"name":"Scene"}', "model": FIXED_EDITOR_MODEL}
    assert len(seen) == 1
    assert seen[0]["text"] == FORMAT
    assert seen[0]["max_output_tokens"] == 20000
    assert seen[0]["model"] == FIXED_EDITOR_MODEL
    assert seen[0]["input"][0] == {"role": "system", "content": "script editor"}
    assert seen[0]["store"] is False
    assert seen[0]["stream"] is False
    if with_image:
        assert seen[0]["input"][1]["content"][0]["type"] == "input_image"
    with pytest.raises(OAuthError, match="cannot be overridden"):
        await grok.complete(PromptRequest(prompt="idea", model="other"), output_schema=SCHEMA)
    assert len(seen) == 1


@pytest.mark.parametrize("image_count", [1, 2])
async def test_structured_images_preserve_bounded_chunks_and_length(image_count):
    schema = {**SCHEMA, "description": "long schema " * 10000}
    output_text = {"format": {**FORMAT["format"], "schema": schema}}
    with tempfile.TemporaryFile() as first, tempfile.TemporaryFile() as second:
        first.write(b"a" * (BUFFER_BYTES + 7))
        second.write(b"b" * (BUFFER_BYTES + 11))
        first.seek(0)
        second.seek(0)
        images = [(first, "image/png"), (second, "image/png")][:image_count]
        body, length = images_json_body("pin", "system", "idea", images,
                                       output_text=output_text, max_output_tokens=20000)
        chunks = [chunk async for chunk in body]
        assert max(map(len, chunks)) <= 65536
        assert sum(map(len, chunks)) == length
        value = json.loads(b"".join(chunks))
        assert value["text"] == output_text
        assert value["max_output_tokens"] == 20000
        assert sum(part["type"] == "input_image"
                   for part in value["input"][1]["content"]) == image_count


async def test_structured_provider_rejection_does_not_retry_or_fallback():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": "unsupported schema"})

    with pytest.raises(OAuthError, match="not retried"):
        await Grok(FakeManager(handler), FIXED_EDITOR_MODEL).complete(
            PromptRequest(prompt="idea"), output_schema=SCHEMA)
    assert len(seen) == 1
    assert seen[0]["text"] == FORMAT
    assert seen[0]["max_output_tokens"] == 20000


def test_public_editor_cannot_supply_internal_schema():
    with pytest.raises(ValidationError):
        PromptRequest(prompt="idea", output_schema=SCHEMA)

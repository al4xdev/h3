"""Public requests and durable run state (no model inference imports)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

PROMPT_ROOT = Path(__file__).resolve().parents[3] / "prompts"
DEFAULT_PROMPT = (PROMPT_ROOT / "initial.md").read_text(encoding="utf-8")
CONTINUATION_PROMPT = (PROMPT_ROOT / "continuation.md").read_text(encoding="utf-8")
RunState = Literal[
    "queued", "running", "ready_for_review", "accepted", "rejected", "failed", "interrupted"
]


@dataclass(frozen=True)
class Settings:
    project_root: Path = Path(__file__).resolve().parents[3]
    comfy_url: str = "http://127.0.0.1:8001"
    comfy_root: Path = Path("/home/alex/comfyui")
    comfy_pid: int | None = None
    inference_deadline: float = 1200.0
    minimum_available_bytes: int = 1536 * 1024**2
    memory_check_interval: float = 5.0
    workflow_output_profile: Literal["baseline", "final_only"] = "baseline"

    def __post_init__(self) -> None:
        if self.workflow_output_profile not in ("baseline", "final_only"):
            raise ValueError("Workflow output profile must be baseline or final_only")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            project_root=Path(os.getenv("H3_PROJECT_ROOT", str(cls.project_root))).resolve(),
            comfy_url=os.getenv("H3_COMFY_URL", cls.comfy_url),
            comfy_root=Path(os.getenv("H3_COMFY_ROOT", str(cls.comfy_root))).resolve(),
            comfy_pid=int(os.environ["H3_COMFY_PID"]) if os.getenv("H3_COMFY_PID") else None,
            inference_deadline=float(os.getenv("H3_INFERENCE_DEADLINE", "1200")),
            workflow_output_profile=os.getenv("H3_WORKFLOW_OUTPUT_PROFILE", "baseline"),
        )


class ImageReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_root: Literal["assets", "inputs", "runs"]
    path: str = Field(min_length=1, max_length=1024, strict=True)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if (value.startswith("/") or "\\" in value or any(ord(c) < 32 for c in value)
                or any(part in {"", ".", ".."} for part in value.split("/"))):
            raise ValueError("Image reference must be a safe relative path")
        return value


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    image: str = "dance_reference.png"
    images: list[str] = Field(default_factory=list, max_length=8)
    references: list[ImageReference] = Field(default_factory=list, max_length=8)
    prompt: str = Field(default=DEFAULT_PROMPT, min_length=1, max_length=12000)
    duration_seconds: float = Field(default=2.3, gt=0, le=3, allow_inf_nan=False)

    @model_validator(mode="after")
    def exclusive_references(self) -> RunRequest:
        if self.references and (self.images or self.image != "dance_reference.png"):
            raise ValueError("Explicit references cannot be mixed with legacy image aliases")
        return self


class ContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    prompt: str | None = Field(default=None, min_length=1, max_length=12000)
    duration_seconds: float = Field(default=2.3, gt=0, le=3, allow_inf_nan=False)
    reference_tail_seconds: Literal[2, 3] = 3
    include_audio: bool = True


class Run(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    state: RunState = "queued"
    created_at: str
    updated_at: str
    seed: int
    prompt: str
    duration_seconds: float
    workflow_hash: str
    parent_id: str | None = None
    prompt_id: str | None = None
    references: list[dict] = Field(default_factory=list)
    input_info: dict = Field(default_factory=dict)
    progress: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    publication_mode: str | None = None
    decision: dict | None = None
    error: str | None = None
    timings: dict = Field(default_factory=dict)

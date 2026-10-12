"""Public requests and durable run state (no model inference imports)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

DEFAULT_PROMPT = (
    "<Picture 1> A woman performs a gentle, coordinated, non-sexual dance with small "
    "side steps and natural arm and hand movements. Preserve her face, hair and "
    "clothing. Stable camera, consistent background, anatomically natural movement, "
    "fully clothed, SFW."
)
RunState = Literal[
    "queued", "running", "ready_for_review", "accepted", "rejected", "failed", "interrupted"
]


@dataclass(frozen=True)
class Settings:
    project_root: Path = Path(__file__).resolve().parents[2]
    comfy_url: str = "http://127.0.0.1:8001"
    comfy_root: Path = Path("/home/alex/comfyui")
    comfy_pid: int | None = None
    inference_deadline: float = 1200.0
    minimum_available_bytes: int = 1536 * 1024**2
    memory_check_interval: float = 5.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            project_root=Path(os.getenv("H3_PROJECT_ROOT", str(cls.project_root))).resolve(),
            comfy_url=os.getenv("H3_COMFY_URL", cls.comfy_url),
            comfy_root=Path(os.getenv("H3_COMFY_ROOT", str(cls.comfy_root))).resolve(),
            comfy_pid=int(os.environ["H3_COMFY_PID"]) if os.getenv("H3_COMFY_PID") else None,
            inference_deadline=float(os.getenv("H3_INFERENCE_DEADLINE", "1200")),
        )


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    image: str = "dance_reference.png"
    images: list[str] = Field(default_factory=list, max_length=8)
    prompt: str = Field(default=DEFAULT_PROMPT, min_length=1, max_length=12000)
    duration_seconds: float = Field(default=2.3, gt=0, le=3, allow_inf_nan=False)


class ContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: StrictInt = Field(ge=0, le=2**53 - 1)
    prompt: str | None = Field(default=None, min_length=1, max_length=12000)
    duration_seconds: float = Field(default=2.3, gt=0, le=3, allow_inf_nan=False)
    reference_tail_seconds: Literal[2, 3] = 2
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

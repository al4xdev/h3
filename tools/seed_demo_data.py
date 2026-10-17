"""Seed a self-contained demo project root for UI testing (Android emulator).

Never contacts ComfyUI, Grok or a GPU: generation runs through the real Roteiro/RunService
contracts with an in-process fake ComfyUI that publishes small FFmpeg-rendered MP4s
(480x864, 24 fps, exact aligned frame count, AAC audio), so the real backend accepts them.

Usage (fish):
    env PYTHONDONTWRITEBYTECODE=1 uv run python tools/seed_demo_data.py --root /tmp/h3-demo --roteiros 25
    env H3_PROJECT_ROOT=/tmp/h3-demo H3_COMFY_URL=http://127.0.0.1:9 uv run uvicorn \\
        h3_backend.api:app --host 0.0.0.0 --port 8010
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from h3_backend.favorites import Favorites
from h3_backend.generation.dispatcher import RunService
from h3_backend.generation.models import Settings
from h3_backend.generation.workflow import frames_for_duration
from h3_backend.grok import FIXED_EDITOR_MODEL, seed_editor
from h3_backend.roteiro import (
    Block,
    CreatePlan,
    Generate,
    ProposalRequest,
    RemovePlan,
    Roteiro,
    UpdatePlan,
)

SECONDS = 8.0
FONT = next((str(p) for p in (Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
                              Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")) if p.is_file()),
            None)
COLORS = ["0x1d4e5f", "0x2a6f73", "0x3b8686", "0x0f3b4c", "0x4a7c8c", "0x255c6b"]
REFERENCE = {"source_root": "assets", "path": "dance_reference.png"}


def render(path: Path, label: str, color: str, seconds: float):
    frames = frames_for_duration(seconds)
    text = ""
    if FONT:
        # Escape for the drawtext filter; the frame number proves ordering when scrubbing.
        safe = label.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")
        text = (f",drawtext=fontfile={FONT}:text='{safe}':fontsize=40:fontcolor=white:"
                "x=(w-text_w)/2:y=h/3,"
                f"drawtext=fontfile={FONT}:text='frame %{{frame_num}}':fontsize=32:"
                "fontcolor=white:x=(w-text_w)/2:y=h/2")
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:size=480x864:rate=24{text}",
        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
        "-frames:v", str(frames), "-t", f"{frames / 24:.6f}", "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-threads", "2",
        "-c:a", "aac", "-b:a", "64k", str(path),
    ], check=True, capture_output=True, timeout=120)


class DemoComfy:
    """In-process stand-in: no network. Each execute publishes one rendered clip."""

    def __init__(self, root: Path):
        self.output = root / "comfy" / "output" / "seed"
        self.output.mkdir(parents=True, exist_ok=True)
        self.next_label = "H3 demo"
        self.next_seconds = SECONDS
        self.count = 0

    async def ensure_idle(self):
        pass

    async def object_info(self):
        return {}

    async def upload(self, path, name):
        return {"name": name, "subfolder": "seed", "filename": f"seed/{name} [input]", "type": "input"}

    async def execute(self, workflow, *, prompt_id, on_submitted, on_progress, **kwargs):
        await on_submitted(prompt_id)
        name = f"clip-{prompt_id}.mp4"
        await asyncio.to_thread(render, self.output / name, self.next_label,
                                COLORS[self.count % len(COLORS)], self.next_seconds)
        self.count += 1
        await on_progress({"value": 1, "max": 1, "prompt_id": prompt_id})
        return {"outputs": {"34": {"gifs": [{"filename": name, "subfolder": "seed", "type": "output"}]}}}

    async def close(self):
        pass


async def no_telemetry(comfy, path, stop, **kwargs):
    await stop.wait()


def prepare_root(root: Path):
    if (root / ".data").exists():
        raise SystemExit(f"{root}/.data already exists; choose a new --root (nothing was changed)")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("workflows", "prompts"):
        link = root / name
        if not link.exists():
            link.symlink_to(REPO / name, target_is_directory=True)
    # Identity images are read through no-follow directory walks, so assets must be real files.
    if not (root / "assets").exists():
        shutil.copytree(REPO / "assets", root / "assets")


def plan_blocks(count: int, scenes: list[tuple[str, str, int]], seed: int) -> list[dict]:
    """Blocks shaped like the timeline planner output: '<scene> · <beat> — parte i/n'."""
    labels = []
    for scene, beat, parts in scenes:
        labels += [(scene, beat, part, parts) for part in range(1, parts + 1)]
    assert len(labels) == count
    return [Block(id=str(uuid4()), duration_seconds=SECONDS, seed=seed,
                  action=f"{scene} · {beat}" + (f" — parte {part}/{parts}" if parts > 1 else ""),
                  prompt=(f"Block {index + 1}. {beat} ({scene}), slice {part}/{parts}. She keeps the "
                          "original identity and outfit; subtle breathing, blinks, small head "
                          "tilts and fabric motion; the camera drifts slowly.")).model_dump()
            for index, (scene, beat, part, parts) in enumerate(labels)]


async def generate(op: Roteiro, service, comfy: DemoComfy, ident: str, block_id: str,
                   parent_id: str | None, *, label: str, decide: bool | None,
                   target: str | None = None) -> str:
    doc = op.get(ident)
    block = next(b for b in doc.blocks if b.id == block_id)
    run_id = str(uuid4())
    comfy.next_label, comfy.next_seconds = label, block.duration_seconds
    observed = await op.generate(ident, block_id, run_id, Generate(
        expected_revision=doc.revision, prompt=block.prompt, seed=block.seed,
        duration_seconds=block.duration_seconds, parent_id=parent_id, target_run_id=target))
    if observed["admission"] != "admitted":
        raise SystemExit(f"Seed generation not admitted: {observed.get('error')}")
    run = await service.wait_run(run_id)
    if run.state != "ready_for_review":
        raise SystemExit(f"Seed generation ended as {run.state}: {run.error}")
    if decide is not None:
        await service.decide(run_id, decide)
    return run_id


DEMO_SCENES = [{"title": "Estúdio", "beats": [
    {"kind": "action", "action": "Dança lenta de vestido preto", "seconds": 40, "dialogue": None},
    {"kind": "hold", "action": "Respira e olha para a câmera", "seconds": 16, "dialogue": "Pronta?"},
    {"kind": "transition", "action": "Gira e o vestido fica vermelho", "seconds": 16, "dialogue": None},
    {"kind": "action", "action": "Dança de vestido vermelho", "seconds": 24, "dialogue": None}]}]


class DemoPlanner:
    """Offline canned answers for the director, critic and prompt-writer steps."""

    async def complete(self, request, *, output_schema=None, schema_name=None):
        marker = "Payload:\n"
        body = json.loads(request.prompt[request.prompt.index(marker) + len(marker):])
        if schema_name == "h3_roteiro_script":
            count = body["block_count"]
            value = {"name": "Dança neon (proposta)", "summary": "Demo offline, sem ato extra.",
                     "events": [{
                         "title": "Estúdio", "kind": "action", "intent": "dança lenta",
                         "dialogue": None,
                         "anatomy": [f"corpo {n}" for n in range(1, count + 1)],
                         "expressions": [f"expressão {n}" for n in range(1, count + 1)],
                         "deltas": [f"delta {n}" for n in range(1, count + 1)],
                         "camera_focus": None, "keeps": ["estúdio"],
                     }]}
        elif schema_name == "h3_roteiro_palette":
            size = body["count"]
            value = {"title": body["title"],
                     "anatomy": [f"corpo {n}" for n in range(1, size + 1)],
                     "expressions": [f"expressão {n}" for n in range(1, size + 1)],
                     "deltas": [f"delta {n}" for n in range(1, size + 1)]}
        else:
            value = {"id": body["id"], "title": body["title"],
                     "expression": body["expression"], "anatomy": body["anatomy"],
                     "delta": body["delta"], "camera_focus": body.get("camera_focus"),
                     "dialogue": body.get("dialogue"),
                     "instruction": (
                         f"Ação: {body['intent']}\nCorpo: {body['anatomy']}\n"
                         f"Expressão: {body['expression']}\n"
                         f"Mudança em relação ao anterior: {body['delta']}\n")}
        return {"text": json.dumps(value, ensure_ascii=False), "model": FIXED_EDITOR_MODEL}


PLACES = ["Estúdio", "Varanda", "Praia", "Cozinha", "Terraço", "Biblioteca", "Rua molhada",
          "Jardim", "Sala de ensaio", "Corredor de hotel", "Telhado", "Floresta", "Escadaria"]
BEATS = [("action", "Dança lenta com giros suaves"), ("hold", "Respira e olha para a câmera"),
         ("transition", "Caminha até a próxima marca"), ("action", "Gira a saia e sorri"),
         ("hold", "Ajeita o cabelo e pausa"), ("transition", "Vira de costas devagar"),
         ("action", "Senta e conversa com alguém fora de quadro"),
         ("action", "Dança com os braços abertos"), ("hold", "Observa a paisagem em silêncio"),
         ("transition", "O vestido muda de cor durante o giro")]
EXTRA_SIZES = [8, 12, 16, 20, 24, 30, 40, 48, 60, 80]
BIG_SIZES = {3: 200, 7: 450, 11: 1000}


def text_blocks(rng: random.Random, count: int) -> list[dict]:
    """Planner-shaped text blocks: scenes of sustained beats split into parts."""
    labels = []
    while len(labels) < count:
        place = rng.choice(PLACES)
        for _ in range(rng.randint(2, 4)):
            kind, beat = rng.choice(BEATS)
            parts = rng.randint(1, 3) if kind != "action" else rng.randint(2, 7)
            labels += [(place, kind, beat, part, parts) for part in range(1, parts + 1)]
    return [Block(id=str(uuid4()), duration_seconds=SECONDS, seed=rng.randint(0, 2**31),
                  action=f"{place} · {beat}" + (f" — parte {part}/{parts}" if parts > 1 else ""),
                  prompt=(f"{beat} in the {place.lower()}, slice {part}/{parts} ({kind}). She keeps "
                          "the original identity and outfit; blinks, breathes, tilts her head and "
                          "shifts her weight; hair and fabric move softly; slow camera drift.")
                  ).model_dump() for place, kind, beat, part, parts in labels[:count]]


async def extra_roteiros(op: Roteiro, count: int) -> list[str]:
    """Text-only roteiros for library load: no runs, no videos, no provider."""
    rng = random.Random(2026101605)
    created = []
    for index in range(count):
        size = BIG_SIZES.get(index, EXTRA_SIZES[index % len(EXTRA_SIZES)])
        place = PLACES[index % len(PLACES)]
        idea = (f"Ela começa em {place.lower()}, alterna danças longas com pausas para respirar e "
                f"termina em {rng.choice(PLACES).lower()}.")
        kind = "adopted" if index in BIG_SIZES or index % 3 != 1 else (
            "proposal" if index % 2 else "draft")
        name = f"{place} · roteiro {index + 1} " + (
            f"(proposta de {min(size, 40)} blocos)" if kind == "proposal" else f"({size} blocos)")
        blocks = text_blocks(rng, size) if kind != "proposal" else []
        doc = await op.create(CreatePlan(name=name, idea=idea, reference=REFERENCE,
                                         adopted=kind == "adopted", blocks=blocks))
        if kind == "proposal":
            await op.propose(doc["id"], ProposalRequest(
                expected_revision=doc["revision"], count=min(size, 40),
                duration_seconds=SECONDS, seed=index), DemoPlanner())
        created.append(doc["id"])
    return created


async def seed(root: Path, extra: int):
    started = time.monotonic()
    prepare_root(root)
    seed_editor(root)
    settings = Settings(project_root=root, comfy_root=root / "comfy", comfy_url="http://127.0.0.1:9")
    comfy = DemoComfy(root)
    service = RunService(settings, comfy=comfy, telemetry=no_telemetry)
    # The fake ComfyUI exposes no node catalog; graph validation is a live-ComfyUI concern.
    service.builder.validate_object_info = lambda info, *, operation: None
    op = Roteiro(service)
    try:
        # (a) 60-block roteiro: accepted prefix, a removed middle block (cut), a rejected block,
        # an inserted bridge awaiting review and planned blocks.
        scenes = [("Estúdio", "Dança lenta de vestido preto", 15),
                  ("Estúdio", "Respira e olha para a câmera", 5),
                  ("Estúdio", "Gira e o vestido fica vermelho", 6),
                  ("Varanda", "Caminha até a janela", 10),
                  ("Varanda", "Dança de vestido vermelho", 14),
                  ("Varanda", "Acena e se despede", 10)]
        long_doc = await op.create(CreatePlan(
            name="Dança neon · 60 blocos", idea="Ela dança de preto, o vestido vira vermelho e ela "
            "termina na varanda acenando.", reference=REFERENCE, adopted=True,
            blocks=plan_blocks(60, scenes, 2026101205)))
        ident = long_doc["id"]
        runs, parent = [], None
        for index, block in enumerate(op.get(ident).blocks[:46]):
            parent = await generate(op, service, comfy, ident, block.id, parent,
                                    label=f"Bloco {index + 1}", decide=True)
            runs.append(parent)
            print(f"accepted {index + 1}/46", flush=True)
        doc = op.get(ident)
        op.remove_block(ident, doc.blocks[20].id, RemovePlan(expected_revision=doc.revision))
        doc = op.get(ident)
        await generate(op, service, comfy, ident, doc.blocks[45].id, runs[-1],
                       label="Bloco recusado", decide=False)
        doc = op.get(ident)
        inserted = Block(id=str(uuid4()), duration_seconds=SECONDS, seed=7,
                         action="Estúdio · Intermediário inserido",
                         prompt="Bridge: she turns slowly toward the next pose, breathing, "
                                "fabric moving softly.")
        blocks = [*doc.blocks[:30], inserted, *doc.blocks[30:59]]  # Keep 60 blocks in total.
        await op.update(ident, UpdatePlan(name=doc.name, idea=doc.idea, reference=doc.reference,
                                          adopted=True, blocks=blocks, expected_revision=doc.revision))
        doc = op.get(ident)
        previous = op.selected_attempt(doc, doc.blocks[29].id).run_id
        following = op.selected_attempt(doc, doc.blocks[31].id).run_id
        await generate(op, service, comfy, ident, inserted.id, previous, label="Ponte (revisar)",
                       decide=None, target=following)
        print("long roteiro done", flush=True)

        # (b) a small fully accepted roteiro.
        small = await op.create(CreatePlan(
            name="Praia ao pôr do sol", idea="Caminhada curta na praia.", reference=REFERENCE,
            adopted=True, blocks=plan_blocks(5, [("Praia", "Caminha na areia", 5)], 42)))
        parent = None
        for index, block in enumerate(op.get(small["id"]).blocks):
            parent = await generate(op, service, comfy, small["id"], block.id, parent,
                                    label=f"Praia {index + 1}", decide=True)
        print("small roteiro done", flush=True)

        # (c) a proposal-only roteiro, planned by the offline fake planner, never adopted.
        draft = await op.create(CreatePlan(name="Ideia nova", idea="Ela dança devagar e diz "
                                           '"Pronta?" antes de girar.', reference=REFERENCE))
        await op.propose(draft["id"], ProposalRequest(expected_revision=draft["revision"], count=12,
                                                      duration_seconds=SECONDS, seed=9), DemoPlanner())
        extras = await extra_roteiros(op, extra)
        favorites = Favorites(service)
        for favorite in (ident, small["id"], *extras[:1]):
            favorites.select("roteiro", favorite, True)
        summary = op.summary()
    finally:
        await service.shutdown()
    runs = sum(1 for path in (root / ".data" / "runs").iterdir() if path.is_dir())
    for item in summary["items"]:
        print(f"{item['block_count']:5d} blocos  {item['states']}  {item['name']}")
    print(f"roteiros={summary['total']} blocks={sum(i['block_count'] for i in summary['items'])} "
          f"runs={runs} seconds={time.monotonic() - started:.1f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path, help="new demo project root")
    parser.add_argument("--roteiros", type=int, default=25,
                        help="extra text-only roteiros for library load (default 25)")
    args = parser.parse_args()
    asyncio.run(seed(args.root.absolute(), max(0, args.roteiros)))


if __name__ == "__main__":
    main()

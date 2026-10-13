from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import StrictBool

from .infrastructure.grok_image import _directory
from .roteiro import Roteiro, StrictDTO, body, canonical, locked, read_file, response, write_file

router = APIRouter()


class Favorite(StrictDTO):
    kind: Literal["roteiro", "freestyle"]
    id: str


class Selection(StrictDTO):
    favorite: StrictBool


class FavoritesFile(StrictDTO):
    items: list[Favorite]


class Favorites:
    def __init__(self, service):
        self.service = service
        self.root = service.store.root
        self.roteiro = Roteiro(service)

    @staticmethod
    def read(directory):
        try:
            document = FavoritesFile.model_validate(read_file(directory, "favorites.json"))
        except FileNotFoundError:
            return []
        keys = {(item.kind, canonical(item.id)) for item in document.items}
        if len(keys) != len(document.items) or len(keys) > 1000:
            raise ValueError("Invalid favorites catalog")
        return document.items

    def resolve(self, kind, ident):
        canonical(ident)
        if kind == "roteiro":
            doc = self.roteiro.get(ident)
            return {"id": doc.id, "name": doc.name[:200].encode()[:256].decode(errors="ignore"),
                    "block_count": len(doc.blocks)}
        if kind != "freestyle":
            raise ValueError("Unknown favorite kind")
        run = self.service.store.get(ident)
        return {"id": run.id, "state": run.state,
                "prompt": run.prompt[:160].encode()[:256].decode(errors="ignore"),
                "duration_seconds": run.duration_seconds, "seed": run.seed}

    def catalog(self):
        try:
            with _directory(self.root, (".data", "library")) as directory:
                items = self.read(directory)
        except FileNotFoundError:
            items = []
        resolved = []
        for item in items:
            try:
                value = self.resolve(item.kind, item.id)
            except FileNotFoundError:
                continue
            resolved.append({**item.model_dump(), "item": value})
        return {"items": resolved, "total": len(resolved)}

    def select(self, kind, ident, selected):
        try:
            self.resolve(kind, ident)
        except FileNotFoundError:
            if selected:
                raise
            removed = (self.roteiro.removed(ident) if kind == "roteiro"
                       else self.service.store.removed(ident))
            if not removed:
                raise
        with (_directory(self.root, (".data", "library"), create=True) as directory,
              locked(directory)):
            items = self.read(directory)
            key = (kind, ident)
            items = [item for item in items if (item.kind, item.id) != key]
            if selected:
                if len(items) >= 1000:
                    raise ValueError("Favorites catalog exceeds capacity")
                items.append(Favorite(kind=kind, id=ident))
            write_file(directory, "favorites.json", {
                "items": [item.model_dump() for item in items]})
        return self.catalog()

    def freestyle(self, limit, offset):
        owned = {attempt["run_id"] for doc in self.roteiro.list()["items"]
                 for attempt in doc["attempts"] if attempt.get("run_id")}
        items, total = self.service.store.list_runs(
            limit=limit, offset=offset, excluded_ids=frozenset(owned))
        return {"items": [run.model_dump() for run in items], "total": total}


@router.get("/favorites")
async def favorites(request: Request):
    return response(Favorites(request.app.state.service).catalog())


@router.put("/favorites/{kind}/{ident}")
async def select_favorite(kind: Literal["roteiro", "freestyle"], ident: str, request: Request):
    selection = await body(request, Selection)
    return response(Favorites(request.app.state.service).select(kind, ident, selection.favorite))


@router.get("/library/freestyle")
async def freestyle(request: Request, limit: int = Query(12, ge=1, le=100),
                    offset: int = Query(0, ge=0, le=10000)):
    return response(Favorites(request.app.state.service).freestyle(limit, offset))

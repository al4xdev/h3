import hashlib
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

router = APIRouter()
WEB_ROOT = Path(__file__).with_name("web")
ASSETS = {
    "pwa.js": "text/javascript",
    "offline.html": "text/html",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "apple-touch-icon.png": "image/png",
}


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(WEB_ROOT / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@router.get("/service-worker.js", include_in_schema=False)
def service_worker():
    source = (WEB_ROOT / "service-worker.js").read_text()
    digest = hashlib.sha256(source.encode())
    for name in ("offline.html", "app.css", "manifest.webmanifest", *ASSETS):
        path = WEB_ROOT / name
        if path.is_file():
            digest.update(name.encode())
            with path.open("rb") as stream:
                while chunk := stream.read(64 * 1024):
                    digest.update(chunk)
    return Response(source.replace("__CACHE_VERSION__", digest.hexdigest()[:20]),
                    media_type="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


def pwa_asset(filename: str):
    return FileResponse(WEB_ROOT / filename, media_type=ASSETS[filename],
                        headers={"Cache-Control": "no-cache"})


def asset_endpoint(filename: str):
    def endpoint():
        return pwa_asset(filename)
    return endpoint


for filename in ASSETS:
    router.add_api_route(f"/ui/{filename}", asset_endpoint(filename),
                         methods=["GET"], include_in_schema=False)

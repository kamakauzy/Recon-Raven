"""Tile proxy — serves OSM tiles through the local server to avoid CORS/CSP issues."""

from pathlib import Path

import aiohttp
from fastapi import APIRouter, Response

router = APIRouter()

TILE_CACHE_DIR = Path("/var/lib/recon-raven/tile_cache")
TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
SUBDOMAINS = ["a", "b", "c"]


@router.get("/tiles/{z}/{x}/{y}.png")
async def proxy_tile(z: int, x: int, y: int):
    """Proxy and cache an OSM tile."""
    # Check disk cache first
    cache_path = TILE_CACHE_DIR / str(z) / str(x) / f"{y}.png"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Fetch from OSM
    s = SUBDOMAINS[(x + y) % 3]
    url = TILE_URL.format(s=s, z=z, x=x, y=y)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Recon-Raven/0.1"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    # Cache to disk
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(data)
                    return Response(
                        content=data,
                        media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
                else:
                    return Response(status_code=resp.status)
    except Exception:
        return Response(status_code=502)

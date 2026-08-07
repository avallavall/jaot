"""Generate the landing page's art with OpenRouter, offline and once.

Deliberately NOT the usual generative-AI look. The brief is a 19th-century
technical-manual plate — engraved line work, warm paper, no photography, no
people, no gradients — because that is what the existing identity already is:
Fraunces as the display serif, a vintage palette, squared corners, paper grain.
A purple-gradient hero would read as AI slop next to it; an engraving does not.

Assets are written to frontend/public/landing/ and committed. The page never
calls OpenRouter at runtime: a visitor must not pay for a generation, and the
LCP must not depend on a third party.

    OPENROUTER_API_KEY=... python scripts/gen_landing_art.py          # generate missing
    OPENROUTER_API_KEY=... python scripts/gen_landing_art.py --force  # regenerate all

The key is read from the environment and never written to disk or logged.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "frontend" / "public" / "landing"
ENDPOINT = "https://openrouter.ai/api/v1/images"

# Per-image cost sits in the cents; the whole set is about a euro. Seedream is
# the flat-rate option, which keeps the bill predictable.
MODEL = "bytedance-seed/seedream-4.5"

STYLE = (
    "19th-century engraved technical plate from an industrial manual, fine ink "
    "line work and cross-hatching, warm aged paper, muted vintage palette of "
    "sepia, dusty sage green and terracotta, no text, no lettering, no people, "
    "no faces, no logos, no modern UI, no photographic realism, no gradients, "
    "flat matte print texture"
)

PLATES = [
    {
        "name": "workshop",
        "aspect_ratio": "16:9",
        "prompt": (
            "A cabinetmaker's workshop floor seen from above: benches, stacked oak "
            "planks, chairs and shelves in production, tools laid out in order. "
        ),
    },
    {
        "name": "routes",
        "aspect_ratio": "16:9",
        "prompt": (
            "A delivery map plate: a walled town with numbered depots and stops, "
            "cart routes drawn as clean surveyed lines across open country. "
        ),
    },
    {
        "name": "texture",
        "aspect_ratio": "1:1",
        "prompt": (
            "An abstract plate of nothing but paper: laid lines, faint foxing, "
            "a plate impression mark near the edge. Almost empty, very subtle. "
        ),
    },
]


def generate(plate: dict, key: str) -> bytes:
    payload = json.dumps(
        {
            "model": MODEL,
            "prompt": plate["prompt"] + STYLE,
            "aspect_ratio": plate["aspect_ratio"],
        }
    ).encode()

    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read())

    # The response shape carries the image either inline (base64 data URL) or by
    # URL, depending on the provider — handle both rather than assume one.
    for item in body.get("data", []):
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        url = item.get("url") or (item.get("image") or {}).get("url")
        if url and url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1])
        if url:
            with urllib.request.urlopen(url, timeout=180) as image:
                return image.read()

    raise RuntimeError(f"no image in response: {json.dumps(body)[:400]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate existing plates")
    args = parser.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit(
            "OPENROUTER_API_KEY is not set.\n"
            "Set it in this shell only — do not commit it and do not paste it into chat:\n"
            "  export OPENROUTER_API_KEY=...        # bash\n"
            '  $env:OPENROUTER_API_KEY = "..."      # PowerShell'
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for plate in PLATES:
        target = OUT_DIR / f"{plate['name']}.png"
        if target.exists() and not args.force:
            print(f"  {plate['name']}: exists, skipping (--force to regenerate)")
            continue
        print(f"  {plate['name']}: generating…")
        try:
            target.write_bytes(generate(plate, key))
        except urllib.error.HTTPError as error:
            sys.exit(f"{plate['name']}: HTTP {error.code} — {error.read()[:300]!r}")
        print(
            f"  {plate['name']}: wrote {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)"
        )

    print("\nReview every plate before using it. Anything that reads as a product")
    print("screenshot, a real company or a person does not ship.")


if __name__ == "__main__":
    main()

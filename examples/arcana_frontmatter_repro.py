#!/usr/bin/env python3
"""Minimal reproduction — YAML front matter is lost in GWDG ARCANA retrieval.

WHAT THIS SHOWS
    Markdown files uploaded to an ARCANA may carry a YAML metadata header
    ("front matter") — the same mechanism GWDG's own Docling pipeline uses
    for the "Markdown Plus" metadata header (Author, Title, Description, …;
    see https://docs.hpc.gwdg.de/services/ai-services/arcana/docling-process/).
    The test document's header below mirrors that documented example field
    for field, so it is exactly the format the platform itself produces.
    That metadata does NOT survive retrieval: the ``References:`` block the
    gateway appends to an ARCANA-routed chat reply carries only
    ``[RREFn] <filename> (<distance>)`` plus the chunk body starting at its
    first heading. No response field — structured or text — returns the
    per-chunk metadata, so the filename is the only metadata channel left.

    The script uploads ONE small markdown file whose front matter contains
    sentinel strings that occur nowhere in the body, asks a question that can
    only be answered from that file, and then searches the ENTIRE raw
    chat-completion JSON for the sentinels.

EXPECTED (what we would like to be possible)
    Receive the front matter alongside each reference — ideally structured
    per ``[RREFn]`` entry. Today consumers must encode section titles, source
    URLs, and deep-link anchors into the (150-char-capped) file name and
    parse them back out client-side.

OBSERVED (April–June 2026)
    * The stored file still contains the front matter — the management API's
      ``…/files/<name>/download`` endpoint returns it verbatim, so it is not
      stripped at upload.
    * The chat response contains the chunk BODY verbatim, but none of the
      front matter values — identical via the OpenAI SDK and via a plain
      HTTP POST, so this is not a client-SDK artifact but happens at
      index/retrieval time on the server.

HOW TO RUN
    export SAIA_API_KEY=...        # Academic Cloud / SAIA API key
    pip install requests openai    # `openai` optional (plain-HTTP leg runs anyway)
    python arcana_frontmatter_repro.py [--model MODEL] [--keep]

    Creates a throwaway arcana ``fm-repro-<hex>`` and deletes it afterwards;
    pass ``--keep`` to retain it for server-side inspection. The two raw chat
    responses are saved as ``arcana_frontmatter_response_<leg>.json`` into
    ``--json-dir`` (default: current directory) — attach those files to a
    report. The companion notebook ``arcana_frontmatter_repro.ipynb`` walks
    the same steps interactively with the full JSON shown per step.

EXIT CODES
    0   ran to a verdict (see the RESULT block at the end)
    1   operational error (auth, upload, indexing, …)
    2   inconclusive — retrieval did not fire, no statement possible
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

DEFAULT_BASE_URL = "https://chat-ai.academiccloud.de/v1"
# An unknown model makes the gateway answer with an opaque 500, so the
# script verifies the model against GET /models before chatting.
DEFAULT_MODEL = "openai-gpt-oss-120b"

# ── The test document ────────────────────────────────────────────────────
# The metadata header mirrors, field for field, the documented Docling
# "Markdown Plus" metadata-header example
# (https://docs.hpc.gwdg.de/services/ai-services/arcana/docling-process/):
#     Author, Title, Description, Filename, Extension, Number of Pages,
#     Version
# so the header is exactly the format GWDG's own pipeline produces. The
# three free-text fields carry sentinel values that occur nowhere in the
# body; the remaining fields carry this file's real values. If any
# sentinel shows up anywhere in the chat response, the metadata IS
# retrievable (and this script prints "FIXED?").
SENTINEL = "FM-SENTINEL-7D3F"
FILE_NAME = "frontmatter_repro_doc.md"
METADATA_HEADER = {
    "Author": f"{SENTINEL}-AUTHOR",
    "Title": f"{SENTINEL}-TITLE",
    "Description": f"{SENTINEL}-DESCRIPTION",
    "Filename": FILE_NAME,
    "Extension": "md",
    "Number of Pages": "1",
    "Version": "1.0",
}
# Only the sentinel-bearing values are searched for in the response — the
# others (filename, "md", "1.0") are too generic to prove anything, and the
# filename is expected to appear (it is the one channel that survives).
SENTINEL_VALUES = [v for v in METADATA_HEADER.values() if v.startswith(SENTINEL)]
BODY = """\
# Maintenance of the Quendelburg lighthouse

The fictional Quendelburg lighthouse is repainted every seven years with a
weather-resistant mixture of linseed oil and crushed mussel shells, applied
in three layers by the keepers' guild.

The lantern room is cleaned every spring; the Fresnel lens is inspected by
two independent opticians every other year.
"""
# A phrase from the body — proves the chunk text itself IS returned
# verbatim in the References block while the header is not.
BODY_PHRASE = "linseed oil and crushed mussel shells"
QUESTION = (
    "According to the documents, how often is the Quendelburg lighthouse "
    "repainted, and what paint mixture is used?"
)


def build_document() -> str:
    # Unquoted `key: value` lines, exactly like the documented example.
    lines = ["---"]
    lines += [f"{key}: {value}" for key, value in METADATA_HEADER.items()]
    lines += ["---", "", BODY]
    return "\n".join(lines)


# ── ARCANA management API (no OpenAI equivalent exists for these) ────────
# Note the auth scheme difference: the management API takes the RAW key
# (no "Bearer" prefix), the chat endpoint takes "Bearer <key>".


def mgmt_headers(api_key: str) -> dict:
    return {"Authorization": api_key, "Accept": "application/json"}


def arcana_api(base_url: str) -> str:
    return f"{base_url}/arcanas/api/v1"


def create_arcana(base_url: str, api_key: str) -> tuple[str, str]:
    """Create a throwaway arcana; return (name, full chat id ``owner/name``)."""
    name = f"fm-repro-{uuid.uuid4().hex[:8]}"
    resp = requests.post(
        f"{arcana_api(base_url)}/arcana/",
        headers=mgmt_headers(api_key),
        json={"name": name},
        timeout=(10, 60),
    )
    resp.raise_for_status()
    details = requests.get(
        f"{arcana_api(base_url)}/arcana/{quote(name, safe='')}",
        headers=mgmt_headers(api_key),
        timeout=(10, 60),
    )
    details.raise_for_status()
    owner = details.json().get("owner_user_name", "")
    full_id = f"{owner}/{name}" if owner else name
    return name, full_id


def upload_document(base_url: str, api_key: str, name: str, content: str) -> None:
    resp = requests.post(
        f"{arcana_api(base_url)}/arcana/{quote(name, safe='')}/files/",
        headers=mgmt_headers(api_key),
        files={"file": (FILE_NAME, content.encode("utf-8"))},
        timeout=(10, 60),
    )
    resp.raise_for_status()


def generate_index_and_wait(
    base_url: str, api_key: str, name: str, *, timeout: float = 600.0
) -> None:
    """Trigger indexing, then poll until INDEXED (the trigger response is
    unreliable for long builds — 504s happen — so the polled state is
    authoritative)."""
    url = f"{arcana_api(base_url)}/arcana/{quote(name, safe='')}/generate-index"
    try:
        resp = requests.post(url, headers=mgmt_headers(api_key), timeout=(10, 60))
        if resp.status_code != 504:
            resp.raise_for_status()
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        pass  # trigger usually reached the server; poll below decides

    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        time.sleep(5)
        info = requests.get(
            f"{arcana_api(base_url)}/arcana/{quote(name, safe='')}",
            headers=mgmt_headers(api_key),
            timeout=(10, 60),
        )
        info.raise_for_status()
        status = (info.json().get("index_info") or {}).get("index_status", "")
        if status != last_status:
            print(f"    index status: {status or '?'}")
            last_status = status
        if status == "INDEXED":
            return
        if status == "ERROR":
            raise RuntimeError(f"indexing failed: {info.json()}")
    raise TimeoutError(f"index generation did not finish within {timeout:.0f}s")


def download_stored_file(base_url: str, api_key: str, name: str) -> str:
    resp = requests.get(
        f"{arcana_api(base_url)}/arcana/{quote(name, safe='')}"
        f"/files/{quote(FILE_NAME, safe='')}/download",
        headers=mgmt_headers(api_key),
        timeout=(10, 60),
    )
    resp.raise_for_status()
    return resp.text


def delete_arcana(base_url: str, api_key: str, name: str) -> None:
    requests.delete(
        f"{arcana_api(base_url)}/arcana/{quote(name, safe='')}",
        headers=mgmt_headers(api_key),
        timeout=(10, 60),
    )


# ── Chat — once via the OpenAI SDK, once via plain HTTP ──────────────────
# Both POST the same /chat/completions endpoint. The non-standard pieces
# (required for ARCANA routing) are identical in both legs:
#   * body  "arcana": {"id": "<owner>/<name>"}
#   * body  "enable-tools": true
#   * header "inference-service: saia-openai-gateway"  — without it the
#     request still returns 200 OK but NO retrieval is triggered.


def chat_via_openai_sdk(
    base_url: str, api_key: str, model: str, arcana_id: str
) -> dict | None:
    """Returns the response as a dict, or None when `openai` is not installed."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={"inference-service": "saia-openai-gateway"},
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": QUESTION}],
        temperature=0,
        extra_body={"arcana": {"id": arcana_id}, "enable-tools": True},
    )
    return resp.model_dump()


def chat_via_plain_http(
    base_url: str, api_key: str, model: str, arcana_id: str
) -> dict:
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "inference-service": "saia-openai-gateway",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": QUESTION}],
            "temperature": 0,
            "arcana": {"id": arcana_id},
            "enable-tools": True,
        },
        timeout=(10, 300),
    )
    resp.raise_for_status()
    return resp.json()


def available_models(base_url: str, api_key: str) -> list[str] | None:
    """Model ids from GET /models, or None when the listing itself fails."""
    try:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=(10, 60),
        )
        resp.raise_for_status()
        return sorted(m["id"] for m in resp.json().get("data", []))
    except Exception:
        return None


# ── Verdict helpers ──────────────────────────────────────────────────────


def message_content(response: dict) -> str:
    try:
        return response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def sentinels_found(response: dict) -> list[str]:
    """Front matter sentinels present anywhere in the raw response JSON."""
    blob = json.dumps(response, ensure_ascii=False)
    return [v for v in SENTINEL_VALUES if v in blob]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("SAIA_API_KEY", ""))
    parser.add_argument(
        "--keep",
        action="store_true",
        help="do not delete the throwaway arcana (for server-side inspection)",
    )
    parser.add_argument(
        "--json-dir",
        default=".",
        help="directory the raw response JSON files are written to (default: cwd)",
    )
    args = parser.parse_args()
    if not args.api_key:
        print("No API key: set SAIA_API_KEY or pass --api-key.", file=sys.stderr)
        return 1

    base, key = args.base_url.rstrip("/"), args.api_key
    document = build_document()

    # Auth preflight — a stale/wrong key would otherwise surface as an
    # unhelpful 401 traceback halfway through.
    version = requests.get(
        f"{arcana_api(base)}/version", headers=mgmt_headers(key), timeout=(10, 60)
    )
    if version.status_code in (401, 403):
        print(
            f"API key rejected (HTTP {version.status_code}). Check SAIA_API_KEY "
            "(a stale value exported in your shell?) or pass --api-key.",
            file=sys.stderr,
        )
        return 1
    version.raise_for_status()
    print(f"ARCANA API version: {version.json().get('version', '?')}")
    print(f"Model: {args.model}\n")

    models = available_models(base, key)
    if models is not None and args.model not in models:
        print(
            f"Model {args.model!r} is not in GET /models — the gateway would "
            f"answer 500.\nPick one of: {', '.join(models)}",
            file=sys.stderr,
        )
        return 1

    print("[1] Uploading this document:")
    print("    " + "\n    ".join(document.splitlines()) + "\n")

    name, arcana_id = create_arcana(base, key)
    print(f"[2] Created arcana {arcana_id!r}")
    try:
        upload_document(base, key, name, document)
        print(f"[3] Uploaded {FILE_NAME!r}; generating index …")
        generate_index_and_wait(base, key, name)

        stored = download_stored_file(base, key, name)
        stored_has_fm = all(v in stored for v in SENTINEL_VALUES)
        print(
            f"[4] Re-downloaded stored file: front matter "
            f"{'PRESENT' if stored_has_fm else 'MISSING'} in stored copy"
        )

        print(f"[5] Chat via OpenAI SDK … (question: {QUESTION!r})")
        sdk_resp = chat_via_openai_sdk(base, key, args.model, arcana_id)
        if sdk_resp is None:
            print("    `openai` not installed — skipping this leg.")
        print("[6] Chat via plain HTTP POST (same request, no SDK) …")
        http_resp = chat_via_plain_http(base, key, args.model, arcana_id)

        # Persist the raw wire evidence — saved before any verdict so the
        # files exist even when the run turns out inconclusive.
        out_dir = Path(args.json_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_paths = []
        for leg, payload in (("openai_sdk", sdk_resp), ("plain_http", http_resp)):
            if payload is None:
                continue
            path = out_dir / f"arcana_frontmatter_response_{leg}.json"
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            json_paths.append(str(path))
        print(f"[7] Raw response JSON saved: {', '.join(json_paths)}")

        content = message_content(http_resp)
        print("\n────── assistant content (plain-HTTP leg) ──────")
        print(content)
        print("─────────────────────────────────────────────────\n")

        retrieval_fired = "[RREF" in content and FILE_NAME in content
        if not retrieval_fired:
            print(
                "INCONCLUSIVE: no References entry citing the uploaded file —\n"
                "retrieval did not fire (model unavailable for ARCANA, or the\n"
                "inference-service header was dropped?). No statement possible."
            )
            return 2

        body_in_refs = BODY_PHRASE in content
        legs = {"plain HTTP": sentinels_found(http_resp)}
        if sdk_resp is not None:
            legs["OpenAI SDK"] = sentinels_found(sdk_resp)

        print("=" * 65)
        print("RESULT")
        print("=" * 65)
        print(f"[OK]   retrieval fired — References block cites {FILE_NAME}")
        print(
            f"[{'OK' if stored_has_fm else '??'}]   stored file still contains "
            "the front matter (download endpoint)"
        )
        print(
            f"[{'OK' if body_in_refs else '??'}]   chunk BODY text returned "
            f"verbatim in the References block"
        )
        for leg_name, hits in legs.items():
            if hits:
                print(
                    f"[FIXED?] {leg_name}: front matter values present: {hits} — "
                    "metadata IS retrievable on this server version!"
                )
            else:
                print(
                    f"[BUG]  {leg_name}: NONE of the {len(SENTINEL_VALUES)} "
                    "front matter sentinels appear anywhere in the response JSON"
                )
        print(
            "\nThe filename is the only per-chunk metadata that survives "
            "retrieval.\nEXPECTED: front matter (or any per-chunk metadata) "
            "retrievable with each\n[RREFn] reference — ideally as structured "
            "data, alternatively inline."
        )
        return 0
    finally:
        if args.keep:
            print(f"\n--keep: arcana {arcana_id!r} retained for inspection.")
        else:
            delete_arcana(base, key, name)
            print(f"\nCleaned up: deleted arcana {arcana_id!r}.")


if __name__ == "__main__":
    sys.exit(main())

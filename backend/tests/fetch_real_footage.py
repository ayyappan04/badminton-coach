"""Download the openly-licensed real badminton clips used for CV testing.

Deliberately low-volume and polite: files are cached, requests are spaced, and
HTTP 429 triggers exponential backoff. This is not a scraper — it fetches six
specific files, once, by direct URL.

It also regenerates `docs/evidence/real-footage-attribution.md` from the live
Commons metadata, so the CC BY / CC BY-SA attribution requirement is met with
real author and licence data rather than a hand-written guess.

    python -m tests.fetch_real_footage
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.footage_manifest import FOOTAGE, FOOTAGE_DIR  # noqa: E402

UA = {"User-Agent": "badminton-coach-local-testing/1.0 (CV evaluation; low volume)"}
API = "https://commons.wikimedia.org/w/api.php"
SPACING_S = 12


def _get(url: str, timeout: int = 600) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def fetch_file(entry: dict) -> bool:
    dest = FOOTAGE_DIR / entry["file"]
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {entry['key']:20} cached ({dest.stat().st_size/1e6:.1f} MB)")
        return True
    for attempt in range(4):
        try:
            started = time.time()
            dest.write_bytes(_get(entry["url"]))
            print(f"  {entry['key']:20} {dest.stat().st_size/1e6:>7.1f} MB in {time.time()-started:.0f}s")
            return True
        except Exception as exc:  # noqa: BLE001
            wait = 20 * (attempt + 1)
            print(f"  {entry['key']:20} {type(exc).__name__} — backing off {wait}s")
            dest.unlink(missing_ok=True)
            time.sleep(wait)
    return False


def commons_metadata(entry: dict) -> dict:
    """Fetch author + licence for correct attribution."""
    title = "File:" + urllib.parse.unquote(entry["page"].split("File:")[-1])
    params = urllib.parse.urlencode({
        "action": "query", "titles": title, "prop": "imageinfo",
        "iiprop": "extmetadata", "format": "json",
    })
    try:
        data = json.loads(_get(f"{API}?{params}", timeout=60))
        page = next(iter(data["query"]["pages"].values()))
        em = page["imageinfo"][0]["extmetadata"]

        def field(name):
            raw = (em.get(name) or {}).get("value", "")
            # Commons returns HTML fragments; strip tags for a plain credit line.
            import re
            return re.sub(r"<[^>]+>", "", raw).strip() or "—"

        return {"artist": field("Artist"), "licence": field("LicenseShortName"),
                "terms": field("UsageTerms")}
    except Exception:
        return {"artist": "—", "licence": entry["licence"], "terms": "—"}


def write_attribution(rows):
    dest = Path(__file__).resolve().parent.parent.parent / "docs" / "evidence" / "real-footage-attribution.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Real footage — sources and attribution",
        "",
        "Clips used to evaluate the CV pipeline. All are hosted on Wikimedia",
        "Commons under licences that permit download and reuse. The video files",
        "are **not** committed to this repository; run",
        "`python -m tests.fetch_real_footage` to obtain them.",
        "",
        "No BWF or other rights-reserved broadcast footage was downloaded. See",
        "`docs/BWF_MANUAL_TEST_PROTOCOL.md` for how that material is covered.",
        "",
        "| Clip | Scenario | Author / credit | Licence | Source |",
        "|---|---|---|---|---|",
    ]
    for entry, meta in rows:
        lines.append(
            f"| `{entry['key']}` | {entry['scenario']} | {meta['artist'][:70]} | "
            f"{meta['licence']} | [Commons]({entry['page']}) |"
        )
    lines += ["", "Licence terms are reproduced on each linked Commons page.", ""]
    dest.write_text("\n".join(lines))
    print(f"\nwrote {dest}")


def main():
    FOOTAGE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"fetching {len(FOOTAGE)} clips into {FOOTAGE_DIR}\n")
    rows = []
    for i, entry in enumerate(FOOTAGE):
        ok = fetch_file(entry)
        rows.append((entry, commons_metadata(entry)))
        if i < len(FOOTAGE) - 1:
            time.sleep(SPACING_S)
    write_attribution(rows)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Cloud Run / local: build fetcher/config_v2.json from env, scrape."""
import json
import os
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
OUT = BASE / "fetcher" / "config_v2.json"


def main() -> int:
    kw = os.environ.get("FETCHER_KEYWORDS_LIST_JSON")
    portals = os.environ.get("FETCHER_PORTALS_JSON")
    if kw and portals:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        portals_cfg = json.loads(portals)
        cfg = {
            "keywords_list": json.loads(kw),
            "portals": portals_cfg,
        }
        OUT.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
        portal_ids = sorted(
            portals_cfg,
            key=lambda pid: (
                int(portals_cfg[pid].get("order", pid)),
                int(pid),
            ),
        )
    else:
        portal_ids = ["1"]
    args = sys.argv[1:]
    # Only store_true flags (e.g. --no-ocr) may be passed via the
    # JOBS argv — a `--flag value` pair would misparse `value` as
    # the portal id below.
    flags = [a for a in args if a.startswith("-")]
    positional = [a for a in args if not a.startswith("-")]
    only = positional[0] if positional else None
    if only is not None:
        portal_ids = [p for p in portal_ids if p == only]
        if not portal_ids:
            print(f"portal {only} not configured", file=sys.stderr)
            return 2
    rc = 0
    for portal_id in portal_ids:
        rc |= subprocess.call(
            [
                sys.executable,
                str(BASE / "manage.py"),
                "scrape_vacancies",
                str(portal_id),
                *flags,
            ],
            cwd=str(BASE),
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

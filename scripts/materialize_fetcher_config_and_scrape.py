#!/usr/bin/env python3
"""Cloud Run / local: build fetcher/config_v2.json from env then run vacancy scraper."""
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
        cfg = {
            "keywords_list": json.loads(kw),
            "portals": json.loads(portals),
        }
        OUT.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
        portal_ids = sorted(json.loads(portals), key=int)
    else:
        portal_ids = ["1"]
    rc = 0
    for portal_id in portal_ids:
        rc |= subprocess.call(
            [
                sys.executable,
                str(BASE / "manage.py"),
                "scrape_first_vacancy_portal",
                str(portal_id),
            ],
            cwd=str(BASE),
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

"""Archive GitHub daily clone counts using only the Python standard library."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path


def merge_days(previous: list[dict], incoming: list[dict]) -> list[dict]:
    """Keep the highest observed values for each UTC date, including partial days."""
    days: dict[str, dict] = {}
    for row in [*previous, *incoming]:
        day = date.fromisoformat(row["timestamp"][:10]).isoformat()
        count, uniques = row["count"], row["uniques"]
        if type(count) is not int or type(uniques) is not int or not 0 <= uniques <= count:
            raise ValueError(f"Invalid clone counts for {day}")
        old = days.get(day, {"count": 0, "uniques": 0})
        days[day] = {"timestamp": f"{day}T00:00:00Z", "count": max(count, old["count"]), "uniques": max(uniques, old["uniques"])}
    return [days[day] for day in sorted(days)]


def archive(snapshot: Path, output: Path) -> None:
    """Validate and merge the snapshot before writing the archive and badge."""
    incoming = json.loads(snapshot.read_text())
    if not isinstance(incoming.get("clones"), list):
        raise ValueError("Expected a GitHub traffic response with a clones array")
    destination = output / "clones.json"
    previous = json.loads(destination.read_text()) if destination.exists() else {"repository": "Dingent/Dingent", "clones": []}
    if previous["repository"] != "Dingent/Dingent":
        raise ValueError("Archive belongs to another repository")
    rows = merge_days(previous["clones"], incoming["clones"])
    total = sum(row["count"] for row in rows)
    first = rows[0]["timestamp"][:10] if rows else "no data"
    last = rows[-1]["timestamp"][:10] if rows else "no data"
    data = {"repository": "Dingent/Dingent", "first_recorded_date": first, "last_recorded_date": last, "total_clones": total, "clones": rows}
    output.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2) + "\n")
    with (output / "clones.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "count", "uniques"])
        writer.writerows((row["timestamp"][:10], row["count"], row["uniques"]) for row in rows)
    label = f"{total:,}"
    value_width = max(50, len(label) * 8 + 16)
    width = 100 + value_width
    (output / "clones.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="Archived clones: {label}">\n'
        f"  <title>Archived clones: {label}, since {first}</title>\n"
        f'  <rect width="{width}" height="20" rx="3" fill="#555"/>\n'
        f'  <path fill="#007ec6" d="M100 0h{value_width}v20H100z"/>\n'
        '  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">\n'
        '    <text x="50" y="14">Archived clones</text>\n'
        f'    <text x="{100 + value_width / 2}" y="14">{label}</text>\n'
        "  </g>\n</svg>\n"
    )
    (output / "README.md").write_text(
        "# Dingent clone traffic archive\n\n"
        f"**{total:,} archived clones** across {len(rows)} recorded UTC dates ({first} through {last}).\n\n"
        "Daily data: [JSON](clones.json) · [CSV](clones.csv) · [Badge](clones.svg).\n\n"
        "Counts cover only the dates collected here, not the entire lifetime of the repository. "
        "Missing dates are unknown, not zero. Each date keeps the highest count observed, so "
        "overlapping API windows and partial boundary days do not erase previously collected counts. "
        "The latest day may still be incomplete. Daily uniques are provided for each date; "
        "their sum is not the number of distinct people across dates.\n\n"
        "See [setup and methodology](https://github.com/Dingent/Dingent/blob/main/docs/clone-traffic.md).\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive(args.snapshot, args.output)

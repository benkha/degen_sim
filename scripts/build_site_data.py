"""Parse committed weekly reports/*.md files into a single data.json for the website.

Run after generating a new weekly report:

    uv run python scripts/build_site_data.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT_DIR / "reports"
OUTPUT_PATH = ROOT_DIR / "data.json"

SECTION_ALIASES = {
    "Combined (NFL + CFB) Results": "combined",
    "NFL Results": "nfl",
    "CFB Results": "cfb",
}

TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


def parse_table(block: str, metric_col: str):
    lines = [l for l in block.strip().splitlines() if l.strip().startswith("|")]
    if len(lines) < 3:
        return []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        record = dict(zip(header, cells))
        cdf_or_p = float(record[metric_col])
        if metric_col == "cdf":
            p_value = 1 - cdf_or_p
            approx = True
        else:
            p_value = cdf_or_p
            approx = False
        rows.append(
            {
                "name": record["name"],
                "wins": int(record["num_wins"]),
                "losses": int(record["num_losses"]),
                "pushes": int(record["num_pushes"]),
                "p_value": round(p_value, 6),
                "approx": approx,
            }
        )
    rows.sort(key=lambda r: r["p_value"])
    return rows


def parse_report(path: Path):
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    # sections[0] is preamble, then alternating (heading, body)
    body_by_heading = {}
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        body = sections[i + 1]
        body_by_heading[heading] = body

    result = {}
    for heading, key in SECTION_ALIASES.items():
        body = body_by_heading.get(heading, "")
        metric_col = "cdf" if "cdf" in body else "p_value"
        result[key] = parse_table(body, metric_col)
    return result


def main():
    date_re = re.compile(r"degen_sim_(\d{8})\.md$")
    weeks = []
    for path in sorted(REPORTS_DIR.glob("degen_sim_*.md")):
        match = date_re.search(path.name)
        if not match:
            continue
        date_str = match.group(1)
        date = datetime.strptime(date_str, "%Y%m%d")
        tables = parse_report(path)
        weeks.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "label": date.strftime("%b %-d, %Y"),
                **tables,
            }
        )

    pickers = sorted({row["name"] for week in weeks for row in week["combined"]})

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pickers": pickers,
        "weeks": weeks,
    }

    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(weeks)} weeks, {len(pickers)} pickers -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

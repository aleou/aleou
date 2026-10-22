"""Post-process the 3D contribution SVGs: transparent background + streak stats.

Usage: patch_profile_svg.py <username> <svg> [<svg> ...]
Requires GITHUB_TOKEN in the environment.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timezone

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    createdAt
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def graphql(variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def fetch_days(login):
    """Return {date: count} for every day since the account was created."""
    now = datetime.now(timezone.utc)
    created = graphql({"login": login, "from": now.isoformat(), "to": now.isoformat()})["createdAt"]
    days = {}
    # The API only accepts ranges of at most one year
    for year in range(int(created[:4]), now.year + 1):
        start = max(datetime(year, 1, 1, tzinfo=timezone.utc), datetime.fromisoformat(created.replace("Z", "+00:00")))
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        user = graphql({"login": login, "from": start.isoformat(), "to": end.isoformat()})
        for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[date.fromisoformat(day["date"])] = day["contributionCount"]
    return days


def streaks(days):
    today = datetime.now(timezone.utc).date()
    ordered = sorted(d for d in days if d <= today)

    longest = run = 0
    for d in ordered:
        run = run + 1 if days[d] > 0 else 0
        longest = max(longest, run)

    # Today without contributions yet does not break the current streak
    current = 0
    for d in reversed(ordered):
        if days[d] > 0:
            current += 1
        elif d != today:
            break
    return current, longest


def stat(x, y, value, label):
    # Same layout as the "contributions" counter: bold number ending at x, label after it
    return (
        f'<text style="font-size: 32px; font-weight: bold;" x="{x}" y="{y}" '
        f'text-anchor="end" class="fill-strong">{value}</text>'
        f'<text style="font-size: 24px;" x="{x + 10}" y="{y}" '
        f'text-anchor="start" class="fill-fg">{label}</text>'
    )


def patch(path, current, longest, total):
    with open(path, encoding="utf-8") as f:
        svg = f.read()

    # Later CSS rule wins: hide the full-size background rect
    svg = svg.replace("</style>", "\n.fill-bg { fill: none; }</style>", 1)

    # Top-left corner is empty space above the calendar
    y = 60
    block = (
        f'<g id="streaks">{stat(60, y, current, "day streak")}{stat(270, y, longest, "max streak")}'
        f'{stat(530, y, f"{total:,}", "all-time")}</g>'
    )
    svg = re.sub(r'<g id="streaks">.*?</g>', "", svg)
    svg = svg.replace("</svg>", block + "</svg>", 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


def main():
    login, paths = sys.argv[1], sys.argv[2:]
    days = fetch_days(login)
    current, longest = streaks(days)
    total = sum(days.values())
    print(f"current streak: {current}, longest streak: {longest}, total: {total}")
    for path in paths:
        patch(path, current, longest, total)


if __name__ == "__main__":
    main()

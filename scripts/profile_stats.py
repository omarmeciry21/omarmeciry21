"""Generate self-hosted GitHub stats cards (SVG) for the profile README.

Usage: GITHUB_TOKEN=... python scripts/profile_stats.py <login> <out_dir>

Writes stats.svg (overview + streaks) and languages.svg (top languages).
Each SVG follows the viewer's light/dark preference on its own.
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

API = "https://api.github.com/graphql"

IGNORED_LANGUAGES = {
    "Makefile", "CMake", "C", "C++", "Objective-C", "Swift", "Ruby",
    "Batchfile", "Shell", "HTML", "Dockerfile", "PowerShell",
}


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


PROFILE_Q = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    contributionsCollection { contributionYears }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

YEAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def collect(login):
    user = gql(PROFILE_Q, {"login": login})["user"]
    days = {}
    for year in sorted(user["contributionsCollection"]["contributionYears"]):
        start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        end = dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)
        cal = gql(
            YEAR_Q,
            {"login": login, "from": start.isoformat(), "to": end.isoformat()},
        )["user"]["contributionsCollection"]["contributionCalendar"]
        for week in cal["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]

    today = dt.datetime.now(dt.timezone.utc).date()
    ordered = sorted(
        (dt.date.fromisoformat(d), c) for d, c in days.items()
        if dt.date.fromisoformat(d) <= today
    )
    total = sum(c for _, c in ordered)
    last_year = sum(c for d, c in ordered if d > today - dt.timedelta(days=365))

    longest = run = 0
    for _, count in ordered:
        run = run + 1 if count else 0
        longest = max(longest, run)
    current = 0
    for i, (day, count) in enumerate(reversed(ordered)):
        if count:
            current += 1
        elif i == 0 and day == today:
            continue
        else:
            break

    langs = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in IGNORED_LANGUAGES:
                continue
            size, color = langs.get(name, (0, edge["node"]["color"]))
            langs[name] = (size + edge["size"], color or "#8b949e")

    return {
        "total": total,
        "last_year": last_year,
        "current": current,
        "longest": longest,
        "repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "followers": user["followers"]["totalCount"],
        "since": user["createdAt"][:4],
        "years": len(user["contributionsCollection"]["contributionYears"]),
        "langs": sorted(langs.items(), key=lambda kv: kv[1][0], reverse=True),
    }


STYLE = """
<style>
  .bg { fill: #ffffff; stroke: #d0d7de; }
  .title { font: 600 16px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #203A43; }
  .label { font: 400 12px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #57606a; }
  .value { font: 700 22px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #1f2328; }
  .accent { fill: #2C9F6B; }
  .track { fill: #eaeef2; }
  .sep { stroke: #d0d7de; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #0d1117; stroke: #30363d; }
    .title { fill: #7ee2b8; }
    .label { fill: #8b949e; }
    .value { fill: #e6edf3; }
    .accent { fill: #3DDC84; }
    .track { fill: #21262d; }
    .sep { stroke: #30363d; }
  }
</style>
"""


def fmt(n):
    return f"{n / 1000:.1f}k" if n >= 10000 else f"{n:,}"


def stats_svg(s):
    w, h = 495, 195
    cells = [
        ("Total contributions", fmt(s["total"]), "all time"),
        ("Last 12 months", fmt(s["last_year"]), "contributions"),
        ("Current streak", fmt(s["current"]), "days"),
        ("Longest streak", fmt(s["longest"]), "days"),
        ("Public repos", fmt(s["repos"]), f"{fmt(s['stars'])} stars · {fmt(s['followers'])} followers"),
        ("Years active", fmt(s["years"]), f"since {s['since']}"),
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="GitHub stats">',
        STYLE,
        f'<rect class="bg" x="0.5" y="0.5" rx="10" width="{w - 1}" height="{h - 1}"/>',
        '<text class="title" x="22" y="34">GitHub activity</text>',
        f'<line class="sep" x1="22" y1="46" x2="{w - 22}" y2="46"/>',
    ]
    col_w = (w - 44) / 3
    for i, (label, value, sub) in enumerate(cells):
        x = 22 + (i % 3) * col_w
        y = 82 + (i // 3) * 64
        parts.append(f'<text class="value" x="{x:.0f}" y="{y}">{escape(value)}</text>')
        parts.append(f'<text class="label" x="{x:.0f}" y="{y + 18}">{escape(label)}</text>')
        parts.append(f'<text class="label accent" x="{x:.0f}" y="{y + 33}">{escape(sub)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def langs_svg(s, top=6):
    langs = s["langs"][:top]
    w, h = 340, 195
    total = sum(size for _, (size, _) in langs) or 1
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Top languages">',
        STYLE,
        f'<rect class="bg" x="0.5" y="0.5" rx="10" width="{w - 1}" height="{h - 1}"/>',
        '<text class="title" x="22" y="34">Top languages</text>',
        f'<line class="sep" x1="22" y1="46" x2="{w - 22}" y2="46"/>',
        '<clipPath id="bar"><rect x="22" y="62" width="296" height="10" rx="5"/></clipPath>',
        '<rect class="track" x="22" y="62" width="296" height="10" rx="5"/>',
        '<g clip-path="url(#bar)">',
    ]
    x = 22.0
    for _, (size, color) in langs:
        seg = 296 * size / total
        parts.append(f'<rect x="{x:.2f}" y="62" width="{seg + 0.5:.2f}" height="10" fill="{color}"/>')
        x += seg
    parts.append("</g>")
    for i, (name, (size, color)) in enumerate(langs):
        cx = 22 + (i % 2) * 150
        cy = 98 + (i // 2) * 30
        pct = 100 * size / total
        parts.append(f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{color}"/>')
        parts.append(f'<text class="label" x="{cx + 16}" y="{cy}"><tspan class="value" style="font-size:13px">{escape(name)}</tspan>  {pct:.1f}%</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    login, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    s = collect(login)
    with open(os.path.join(out, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg(s))
    with open(os.path.join(out, "languages.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg(s))
    print(json.dumps({k: v for k, v in s.items() if k != "langs"}))
    print([name for name, _ in s["langs"][:6]])


if __name__ == "__main__":
    main()

"""Generate every visual of the profile README from live GitHub data.

Usage: generate_profile.py <username> <out_dir>
Requires GITHUB_TOKEN in the environment (a token that can read private
contributions gives the full picture).

Writes to <out_dir>:
  header.svg, linkedin.svg, footer.svg        theme-independent banners
  about-<theme>.svg                           terminal-style intro
  stack-<theme>.svg                           tools grouped by domain
  project-<repo>-<theme>.svg                  one card per public project
  activity-<theme>.svg                        3D calendar + streaks + totals
"""

import base64
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace"

with open(os.path.join(ROOT, "assets", "icons.json"), encoding="utf-8") as f:
    ICONS = json.load(f)["icons"]

# ---------------------------------------------------------------- content

TAGLINES = [
    "ships CI/CD pipelines and containers",
    "secures identities with Entra ID and SSO",
    "wires systems together with APIs and n8n",
    "runs GenAI on serverless GPUs",
]

CHIPS = ["France", "Higher education IT", "DevOps · IAM · GenAI"]

# (key, value); keys starting with "- " are list items, value None opens a block
ABOUT = [
    ("role", "IT Project Manager — higher education"),
    ("location", "France"),
    ("daily", None),
    ("- devops", "CI/CD, Docker containerization, Traefik/Nginx reverse proxy, Linux VPS deployments"),
    ("- iam", "Entra ID — MFA, conditional access, SSO / OIDC, account lifecycle management"),
    ("- secops", "incident response, sign-in auditing, mail security hardening"),
    ("- data", "ETL & cross-system imports (SIS / ERP / LMS), reconciliation scripts"),
    ("- integ", "REST APIs, webhooks, workflow orchestration (iPaaS / n8n)"),
    ("- run", "web server operations (PHP / LAMP), monitoring, backups, internal MCP servers"),
    ("side", "Proxmox homelab (LXC / VM), serverless GPU, web & mobile apps"),
]

# Icons come from .github/assets/icons.json (simple-icons); tuples are
# brands simple-icons does not ship: (label, monogram, color)
COMFYUI = ("ComfyUI", "C", "#F5B731")
RUNPOD = ("RunPod", "RP", "#673AB7")
STACK = [
    ("LANGUAGES & WEB", ["python", "typescript", "javascript", "php", "fastapi", "nextdotjs", "react", "nodedotjs"]),
    ("INFRA & DEVOPS", ["docker", "linux", "proxmox", "traefikproxy", "nginx", "githubactions", "cloudflare"]),
    ("IDENTITY & DATA", [("Entra ID", "ID", "#0078D4"), ("Azure", "Az", "#0089D6"), "openid", "postgresql", "mongodb"]),
    ("AUTOMATION & AI", ["n8n", "modelcontextprotocol", "anthropic", COMFYUI, RUNPOD, "ffmpeg", "blender"]),
]

LABELS = {
    "traefikproxy": "Traefik",
    "githubactions": "Actions",
    "openid": "OIDC / SSO",
    "modelcontextprotocol": "MCP",
    "anthropic": "Claude",
}

PROJECTS = [
    ("runpod-worker-comfy",
     "ComfyUI exposed as a serverless API on RunPod GPUs — on-demand image & video generation, scale-to-zero.",
     ["python", "docker", COMFYUI, RUNPOD]),
    ("FFMPEGWorker", "FFmpeg video-processing API worker driven by a job queue.", ["python", "ffmpeg", "docker"]),
]

THEMES = {
    "dark": {
        "card": "#0f1720", "tile": "#141f29", "border": "#24323f",
        "text": "#e6edf3", "muted": "#8b949e", "track": "#22303c",
        "accent": "#2EC4B6", "accent2": "#4cc9f0",
        "cal_empty": "#1d2833", "cal": ["#0f5c55", "#15877c", "#22b3a4", "#62e3d5"],
        "term": "#0b1118", "term_bar": "#16212b",
        "key": "#7ee0d6", "str": "#d2dbe4", "dash": "#ff9f6b", "lineno": "#3b4b5a",
    },
    "light": {
        "card": "#f6f8fa", "tile": "#ffffff", "border": "#d0d7de",
        "text": "#1f2328", "muted": "#59636e", "track": "#e3e8ee",
        "accent": "#0f9488", "accent2": "#0284c7",
        "cal_empty": "#e4e9ee", "cal": ["#b3ebe4", "#62d1c4", "#1fa797", "#0b6e66"],
        "term": "#ffffff", "term_bar": "#eef2f5",
        "key": "#0f766e", "str": "#24292f", "dash": "#c2410c", "lineno": "#b6c0ca",
    },
}

FLAME = (
    "M0,-34 C10,-22 24,-10 22,8 C20,24 8,32 0,32 C-8,32 -22,24 -22,8 "
    "C-22,-4 -14,-12 -10,-20 C-8,-10 -4,-6 0,-4 C4,-12 4,-22 0,-34 Z"
)
FLAME_CORE = "M0,-6 C6,2 12,8 10,18 C8,26 -8,26 -10,18 C-12,10 -6,4 0,-6 Z"

# octicons star-16 / repo-forked-16
STAR = ("M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 "
        "01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611"
        "L7.327.668A.75.75 0 018 .25z")
FORK = ("M5 3.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm0 2.122a2.25 2.25 0 10-1.5 0v.878A2.25 2.25 0 005.75 8.5h1.5"
        "v2.128a2.251 2.251 0 101.5 0V8.5h1.5a2.25 2.25 0 002.25-2.25v-.878a2.25 2.25 0 10-1.5 0v.878a.75.75 0 01-.75"
        ".75h-4.5A.75.75 0 015 6.25v-.878zm3.75 7.378a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm3-8.75a.75.75 0 100-1.5.75"
        ".75 0 000 1.5z")


# ---------------------------------------------------------------- data

def graphql(query, variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt avatarUrl(size: 200)
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      totalCount
      nodes {
        name isPrivate stargazerCount forkCount pushedAt
        primaryLanguage { name color }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      restrictedContributionsCount
      contributionCalendar { totalContributions }
    }
  }
}
"""

REPO_QUERY = """
query($login: String!, $name: String!) {
  repository(owner: $login, name: $name) {
    name stargazerCount forkCount pushedAt
    primaryLanguage { name color }
  }
}
"""

CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_days(login, created):
    """Return {date: count} for every day since the account was created."""
    now = datetime.now(timezone.utc)
    created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
    days = {}
    # The API only accepts ranges of at most one year
    for year in range(created_at.year, now.year + 1):
        start = max(datetime(year, 1, 1, tzinfo=timezone.utc), created_at)
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        user = graphql(CALENDAR_QUERY, {"login": login, "from": start.isoformat(), "to": end.isoformat()})["user"]
        for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[date.fromisoformat(day["date"])] = day["contributionCount"]
    return days


def streaks(days, today):
    """Return ((current, start, end), (longest, start, end))."""
    ordered = sorted(d for d in days if d <= today)

    best = (0, None, None)
    run, run_start = 0, None
    for d in ordered:
        if days[d] > 0:
            run_start = d if run == 0 else run_start
            run += 1
            if run > best[0]:
                best = (run, run_start, d)
        else:
            run = 0

    # Today without contributions yet does not break the current streak
    current, cur_start, cur_end = 0, None, None
    for d in reversed(ordered):
        if days[d] > 0:
            current += 1
            cur_start = d
            cur_end = cur_end or d
        elif d != today:
            break
    return (current, cur_start, cur_end), best


def languages(repos, top=5):
    sizes, colors = {}, {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    ranked = sorted(sizes.items(), key=lambda kv: -kv[1])
    result = [(name, size / total, colors[name]) for name, size in ranked[:top]]
    rest = sum(size for _, size in ranked[top:]) / total
    if rest > 0:
        result.append(("Other", rest, "#6e7681"))
    return result


def avatar_data_uri(url):
    with urllib.request.urlopen(url) as resp:
        mime = resp.headers.get_content_type()
        return f"data:{mime};base64,{base64.b64encode(resp.read()).decode()}"


# ---------------------------------------------------------------- helpers

def fmt_date(d, today):
    if d is None:
        return "—"
    return f"{d:%b} {d.day}" if d.year == today.year else f"{d:%b} {d.day}, {d.year}"


def fmt_range(start, end, today):
    if start is None:
        return "no streak yet"
    if start == end:
        return fmt_date(start, today)
    return f"{fmt_date(start, today)} – {fmt_date(end, today)}"


def ago(iso, now):
    seconds = (now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("year", 31536000), ("month", 2592000), ("day", 86400), ("hour", 3600)):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


def luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def shade(hex_color, factor):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c * factor))) for c in (r, g, b)))


def wrap(text, width):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line] if line else lines


def svg_open(width, height, label):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
    )


def base_css(t):
    return f"""
  text {{ font-family: {FONT}; fill: {t['text']}; }}
  .mono {{ font-family: {MONO}; }}
  .kicker {{ font-size: 12px; font-weight: 700; letter-spacing: 1.6px; fill: {t['muted']}; }}
  .big {{ font-size: 46px; font-weight: 800; letter-spacing: -1px; }}
  .unit {{ font-size: 18px; font-weight: 600; fill: {t['muted']}; }}
  .small {{ font-size: 13px; }}
  .dim {{ fill: {t['muted']}; }}
  .strong {{ font-weight: 700; }}
  .tile {{ fill: {t['tile']}; stroke: {t['border']}; }}
  .grad {{ fill: url(#accent); }}
  /* Final state is the default; animations start from the hidden state so
     renderers that do not play them still show everything */
  .fade {{ animation: fade .8s ease-out backwards; }}
  .grow {{ transform-box: fill-box; transform-origin: left; animation: grow 1.2s cubic-bezier(.2,.8,.2,1) .4s backwards; }}
  @keyframes fade {{ from {{ opacity: 0; }} }}
  @keyframes grow {{ from {{ transform: scaleX(0); }} }}
"""


def accent_defs(t):
    return (
        f'<linearGradient id="accent" x1="0" x2="1"><stop offset="0" stop-color="{t["accent"]}"/>'
        f'<stop offset="1" stop-color="{t["accent2"]}"/></linearGradient>'
    )


def card(w, h, t):
    return f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20" fill="{t["card"]}" stroke="{t["border"]}"/>'


def icon_tile(item, x, y, size, t, label=True):
    """Solid brand-colored tile with a white or black glyph, like an app icon."""
    if isinstance(item, tuple):
        name, mono, color = item
        glyph_color = "#ffffff" if luminance(color) < 0.62 else "#111111"
        glyph = (f'<text x="{x + size / 2}" y="{y + size / 2 + size * 0.14:.1f}" text-anchor="middle" '
                 f'style="font-size:{size * 0.38:.0f}px;font-weight:800;fill:{glyph_color}">{escape(mono)}</text>')
    else:
        icon = ICONS[item]
        name, color = LABELS.get(item, icon["title"]), icon["hex"]
        glyph_color = "#ffffff" if luminance(color) < 0.62 else "#111111"
        scale = size * 0.54 / 24
        offset = (size - 24 * scale) / 2
        glyph = (f'<path transform="translate({x + offset:.1f} {y + offset:.1f}) scale({scale:.3f})" '
                 f'fill="{glyph_color}" d="{icon["path"]}"/>')
    # Near-black brands get a border so they stay visible on dark cards
    stroke = f' stroke="{t["border"]}"' if luminance(color) < 0.12 else ""
    out = f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{size * 0.26:.0f}" fill="{color}"{stroke}/>{glyph}'
    if label:
        out += (f'<text x="{x + size / 2}" y="{y + size + 20}" text-anchor="middle" class="small dim">'
                f'{escape(name)}</text>')
    return out


# ---------------------------------------------------------------- header

def header_svg(login, avatar):
    w, h = 1200, 300
    cx, cy = 980, 150
    taglines = "".join(
        f'<text x="66" y="214" class="tag" style="animation-delay:{i * 3}s{";opacity:1" if i == 0 else ""}">'
        f'{escape(line)}</text>'
        for i, line in enumerate(TAGLINES)
    )
    chips, x = [], 64
    for chip in CHIPS:
        width = 34 + len(chip) * 7.6
        chips.append(
            f'<g transform="translate({x:.0f} 238)"><rect width="{width:.0f}" height="30" rx="15" '
            f'fill="#ffffff" fill-opacity=".06" stroke="#2EC4B6" stroke-opacity=".35"/>'
            f'<circle cx="16" cy="15" r="3.5" fill="#2EC4B6"/>'
            f'<text x="27" y="20" class="chip">{escape(chip)}</text></g>'
        )
        x += width + 10
    period = len(TAGLINES) * 3

    return f"""{svg_open(w, h, f"{login} — DevOps, IAM, automation, GenAI")}
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0a141c"/><stop offset=".55" stop-color="#12303a"/><stop offset="1" stop-color="#1b4654"/>
  </linearGradient>
  <linearGradient id="title" x1="0" x2="1">
    <stop offset="0" stop-color="#ffffff"/><stop offset=".6" stop-color="#9ef0e6"/><stop offset="1" stop-color="#4cc9f0"/>
  </linearGradient>
  <radialGradient id="blobA"><stop offset="0" stop-color="#2EC4B6" stop-opacity=".5"/><stop offset="1" stop-color="#2EC4B6" stop-opacity="0"/></radialGradient>
  <radialGradient id="blobB"><stop offset="0" stop-color="#4cc9f0" stop-opacity=".35"/><stop offset="1" stop-color="#4cc9f0" stop-opacity="0"/></radialGradient>
  <radialGradient id="blobC"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".28"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></radialGradient>
  <radialGradient id="halo"><stop offset=".55" stop-color="#2EC4B6" stop-opacity=".35"/><stop offset="1" stop-color="#2EC4B6" stop-opacity="0"/></radialGradient>
  <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#2EC4B6"/><stop offset="1" stop-color="#8b5cf6"/>
  </linearGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
    <path d="M32 0H0V32" fill="none" stroke="#ffffff" stroke-opacity=".045"/>
  </pattern>
  <clipPath id="card"><rect width="{w}" height="{h}" rx="24"/></clipPath>
  <clipPath id="avatar"><circle cx="{cx}" cy="{cy}" r="72"/></clipPath>
</defs>
<style>
  text {{ font-family: {FONT}; }}
  .prompt {{ font-family: {MONO}; font-size: 16px; fill: #2EC4B6; }}
  .cursor {{ fill: #2EC4B6; animation: blink 1.1s steps(1) infinite; }}
  .name {{ font-size: 96px; font-weight: 800; letter-spacing: -3px; fill: url(#title); }}
  .tag {{ font-size: 22px; fill: #cfe9e6; opacity: 0; animation: tag {period}s infinite; }}
  .chip {{ font-size: 13px; font-weight: 600; fill: #cfe9e6; }}
  .spin {{ transform-origin: {cx}px {cy}px; animation: spin 24s linear infinite; }}
  .spin-rev {{ transform-origin: {cx}px {cy}px; animation: spin 36s linear infinite reverse; }}
  .pulse {{ transform-origin: {cx}px {cy}px; animation: pulse 4s ease-in-out infinite; }}
  @keyframes tag {{ 0% {{ opacity: 0; }} 3% {{ opacity: 1; }} 22% {{ opacity: 1; }} 25% {{ opacity: 0; }} 100% {{ opacity: 0; }} }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  @keyframes pulse {{ 50% {{ transform: scale(1.08); opacity: .6; }} }}
</style>
<g clip-path="url(#card)">
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" fill="url(#grid)"/>
  <circle cx="160" cy="30" r="260" fill="url(#blobA)">
    <animate attributeName="cx" values="160;320;160" dur="14s" repeatCount="indefinite"/>
  </circle>
  <circle cx="1020" cy="300" r="300" fill="url(#blobB)">
    <animate attributeName="cy" values="300;200;300" dur="11s" repeatCount="indefinite"/>
  </circle>
  <circle cx="600" cy="-40" r="220" fill="url(#blobC)">
    <animate attributeName="cx" values="600;500;600" dur="16s" repeatCount="indefinite"/>
  </circle>

  <text x="66" y="74" class="prompt">~ $ whoami<tspan class="cursor"> ▍</tspan></text>
  <text x="58" y="170" class="name">{escape(login)}</text>
  {taglines}
  {''.join(chips)}

  <circle cx="{cx}" cy="{cy}" r="130" fill="url(#halo)" class="pulse"/>
  <g class="spin-rev" fill="none" stroke="#9ef0e6" stroke-opacity=".25">
    <circle cx="{cx}" cy="{cy}" r="118" stroke-dasharray="2 7"/>
  </g>
  <g class="spin">
    <circle cx="{cx}" cy="{cy}" r="98" fill="none" stroke="url(#ringGrad)" stroke-width="2.5" stroke-dasharray="120 34" stroke-linecap="round"/>
    <circle cx="{cx + 98}" cy="{cy}" r="5" fill="#9ef0e6"/>
    <circle cx="{cx - 69}" cy="{cy - 69}" r="3.5" fill="#4cc9f0"/>
  </g>
  <g class="spin-rev">
    <circle cx="{cx}" cy="{cy - 118}" r="4" fill="#8b5cf6"/>
  </g>
  <circle cx="{cx}" cy="{cy}" r="78" fill="#0a141c" stroke="#2EC4B6" stroke-width="2"/>
  <image href="{avatar}" x="{cx - 72}" y="{cy - 72}" width="144" height="144" clip-path="url(#avatar)" preserveAspectRatio="xMidYMid slice"/>
</g>
</svg>
"""


def linkedin_svg():
    w, h = 300, 52
    return f"""{svg_open(w, h, "Connect on LinkedIn")}
<defs>
  <linearGradient id="li" x1="0" x2="1"><stop offset="0" stop-color="#0A66C2"/><stop offset="1" stop-color="#1688d8"/></linearGradient>
</defs>
<rect width="{w}" height="{h}" rx="26" fill="url(#li)"/>
<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="25" fill="none" stroke="#ffffff" stroke-opacity=".25"/>
<path transform="translate(26 14)" fill="#ffffff" d="{ICONS['linkedin']['path']}"/>
<text x="62" y="32" style="font-family:{FONT};font-size:17px;font-weight:700;fill:#ffffff">Connect on LinkedIn</text>
<text x="{w - 28}" y="33" text-anchor="end" style="font-family:{FONT};font-size:18px;font-weight:700;fill:#ffffff">→</text>
</svg>
"""


# ---------------------------------------------------------------- about

def about_svg(t, login):
    w = 1200
    line_h, top = 30, 96
    h = top + len(ABOUT) * line_h + 40
    char_w = 9.1  # 15px monospace advance
    rows = []
    for i, (key, value) in enumerate(ABOUT):
        y = top + i * line_h
        item = key.startswith("- ")
        name = key[2:] if item else key
        parts = f'<tspan fill="{t["dash"]}">- </tspan>' if item else ""
        parts += f'<tspan fill="{t["key"]}" font-weight="700">{escape(name)}</tspan><tspan fill="{t["muted"]}">:</tspan>'
        delay = f"animation-delay:{i * 0.08:.2f}s"
        rows.append(
            f'<text x="64" y="{y}" class="mono" style="font-size:13px;fill:{t["lineno"]}" text-anchor="end">{i + 1}</text>'
            f'<text x="{88 + (2 * char_w if item else 0):.0f}" y="{y}" class="mono fade" style="font-size:15px;{delay}">{parts}</text>'
        )
        if value:
            # Values sit in a fixed column, whatever the key width renders as
            rows.append(f'<text x="{88 + 14 * char_w:.0f}" y="{y}" class="mono fade" '
                        f'style="font-size:15px;fill:{t["str"]};{delay}">{escape(value)}</text>')
    cursor_y = top + len(ABOUT) * line_h

    return f"""{svg_open(w, h, "About")}
<style>{base_css(t)}
  .cursor {{ fill: {t['accent']}; animation: blink 1.1s steps(1) infinite; }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
</style>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20" fill="{t['term']}" stroke="{t['border']}"/>
<path d="M.5 52V20.5a20 20 0 0 1 20-20h{w - 41}a20 20 0 0 1 20 20V52Z" fill="{t['term_bar']}"/>
<line x1="0" y1="52" x2="{w}" y2="52" stroke="{t['border']}"/>
<circle cx="28" cy="26" r="6.5" fill="#ff5f57"/><circle cx="50" cy="26" r="6.5" fill="#febc2e"/><circle cx="72" cy="26" r="6.5" fill="#28c840"/>
<text x="{w / 2}" y="31" text-anchor="middle" class="mono small dim">~/{escape(login)}/about.yaml</text>
<text x="{w - 28}" y="31" text-anchor="end" class="kicker">ABOUT</text>
{''.join(rows)}
<text x="64" y="{cursor_y}" class="mono" style="font-size:13px;fill:{t['lineno']}" text-anchor="end">{len(ABOUT) + 1}</text>
<rect x="88" y="{cursor_y - 15}" width="9" height="19" class="cursor"/>
</svg>
"""


# ---------------------------------------------------------------- stack

def stack_svg(t):
    w = 1200
    row_h, top, size, step = 108, 80, 56, 104
    h = top + len(STACK) * row_h + 4
    rows = []
    for r, (group, items) in enumerate(STACK):
        y = top + r * row_h
        if r:
            rows.append(f'<line x1="48" y1="{y - 16}" x2="{w - 48}" y2="{y - 16}" stroke="{t["border"]}" stroke-dasharray="3 5"/>')
        rows.append(f'<text x="48" y="{y + size / 2 + 4}" class="kicker" style="fill:{t["text"]}">{escape(group)}</text>')
        for i, item in enumerate(items):
            rows.append(f'<g class="fade" style="animation-delay:{r * 0.15 + i * 0.05:.2f}s">'
                        f'{icon_tile(item, 270 + i * step, y, size, t)}</g>')

    return f"""{svg_open(w, h, "Stack")}
<defs>{accent_defs(t)}</defs>
<style>{base_css(t)}</style>
{card(w, h, t)}
<text x="48" y="44" class="kicker">STACK</text>
<rect x="48" y="54" width="44" height="3" rx="1.5" fill="url(#accent)"/>
{''.join(rows)}
</svg>
"""


# ---------------------------------------------------------------- projects

def project_svg(t, repo, blurb, tags, now):
    w, h = 590, 230
    desc = "".join(
        f'<text x="32" y="{108 + i * 22}" style="font-size:15px" class="dim">{escape(line)}</text>'
        for i, line in enumerate(wrap(blurb, 60)[:3])
    )
    tag_tiles = "".join(icon_tile(tag, 32 + i * 40, 170, 30, t, label=False) for i, tag in enumerate(tags))
    lang = repo["primaryLanguage"] or {"name": "—", "color": "#8b949e"}

    return f"""{svg_open(w, h, repo['name'])}
<defs>{accent_defs(t)}</defs>
<style>{base_css(t)}</style>
{card(w, h, t)}
<text x="32" y="44" class="kicker">PUBLIC PROJECT</text>
<text x="{w - 32}" y="44" text-anchor="end" class="small dim">updated {ago(repo['pushedAt'], now)}</text>
<text x="32" y="78" style="font-size:26px;font-weight:800" class="grad">{escape(repo['name'])}</text>
{desc}
{tag_tiles}
<g transform="translate({w - 196} 190)">
  <circle cx="6" cy="-4" r="6" fill="{lang['color']}"/>
  <text x="18" y="1" class="small">{escape(lang['name'])}</text>
  <path transform="translate(98 -13)" d="{STAR}" fill="{t['muted']}"/>
  <text x="120" y="1" class="small strong">{repo['stargazerCount']}</text>
  <path transform="translate(140 -13)" d="{FORK}" fill="{t['muted']}"/>
  <text x="160" y="1" class="small strong">{repo['forkCount']}</text>
</g>
</svg>
"""


# ---------------------------------------------------------------- activity

def calendar_3d(t, days, today, ox, oy):
    """Isometric bars for the last 53 weeks, Sunday-first like GitHub."""
    first = today - timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)
    cells = []
    for wk in range(53):
        for d in range(7):
            day = first + timedelta(days=wk * 7 + d)
            if day <= today:
                cells.append((wk, d, day, days.get(day, 0)))

    counts = sorted(c for *_, c in cells if c > 0)
    peak = counts[-1] if counts else 1
    quart = [counts[int(len(counts) * q)] for q in (.25, .5, .75)] if counts else [1, 1, 1]

    week = (18.4, 5.4)      # one week to the right
    weekday = (-9.5, 8.6)   # one weekday down-left

    def pt(wk, d, lift=0.0):
        return ox + wk * week[0] + d * weekday[0], oy + wk * week[1] + d * weekday[1] - lift

    def poly(points, fill):
        return '<path d="M' + " L".join(f"{x:.1f},{y:.1f}" for x, y in points) + f'Z" fill="{fill}"/>'

    bars = []
    # Back to front so nearer bars overlap the ones behind
    for wk, d, day, count in sorted(cells, key=lambda c: c[0] + c[1]):
        if count:
            color = t["cal"][sum(count > q for q in quart)]
            lift = 6 + 92 * (count / peak) ** 0.7
        else:
            color = t["cal_empty"]
            lift = 2
        corners = [pt(wk, d, lift), pt(wk + 1, d, lift), pt(wk + 1, d + 1, lift), pt(wk, d + 1, lift)]
        # Shrink each block a little so cells read as separate
        mx, my = (corners[0][0] + corners[2][0]) / 2, (corners[0][1] + corners[2][1]) / 2
        top = [(mx + (x - mx) * .88, my + (y - my) * .88) for x, y in corners]
        base = [(x, y + lift) for x, y in top]
        faces = (
            poly([top[1], top[2], base[2], base[1]], shade(color, .62))
            + poly([top[2], top[3], base[3], base[2]], shade(color, .8))
            + poly(top, color)
        )
        title = f"<title>{day.isoformat()}: {count} contribution{'s' if count != 1 else ''}</title>"
        extra = ' class="bar today"' if day == today else ' class="bar"'
        bars.append(f'<g{extra} style="animation-delay:{wk * 0.018:.3f}s">{title}{faces}</g>')
    return "".join(bars)


def activity_svg(t, today, since, days, cur, best, total, last_year, private_share,
                 private_repos, repo_count, langs):
    w, h = 1200, 860
    current, cur_start, cur_end = cur
    longest, best_start, best_end = best
    ratio = 1 if longest == 0 else min(current / longest, 1)
    is_best = current > 0 and current >= longest

    # Year insights for the empty corner of the 3D panel
    year_days = {d: c for d, c in days.items() if today - timedelta(days=365) < d <= today}
    best_day = max(year_days, key=lambda d: year_days[d]) if year_days else today
    weekday_totals = [0] * 7
    for d, c in year_days.items():
        weekday_totals[d.weekday()] += c
    top_weekday = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"][
        weekday_totals.index(max(weekday_totals))]
    active_days = sum(1 for c in year_days.values() if c)

    scale = "".join(
        f'<rect x="{80 + i * 18}" y="459" width="13" height="13" rx="3" fill="{c}"/>'
        for i, c in enumerate([t["cal_empty"]] + t["cal"])
    )

    # Lower half: streaks and totals
    y0 = 520
    r = 84
    circ = 2 * math.pi * r
    ring_cx, ring_cy = 202, y0 + 162

    bar_x, bar_w = 840, 300
    segs, legend, x = [], [], bar_x
    for i, (lang, share, color) in enumerate(langs):
        seg_w = share * bar_w
        segs.append(f'<rect x="{x:.1f}" y="{y0 + 202}" width="{max(seg_w, 0.5):.1f}" height="10" fill="{color}"/>')
        x += seg_w
        lx = bar_x + (i % 2) * 160
        ly = y0 + 238 + (i // 2) * 22
        legend.append(
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 16}" y="{ly}" class="small">{escape(lang)} '
            f'<tspan class="dim">{share * 100:.1f}%</tspan></text>'
        )

    badge = (
        f'<g class="fade" style="animation-delay:.9s"><rect x="{ring_cx - 58}" y="{ring_cy + 122}" width="116" height="22" rx="11" '
        f'fill="url(#flame)"/><text x="{ring_cx}" y="{ring_cy + 137}" class="badge">PERSONAL BEST</text></g>'
        if is_best else
        f'<text x="{ring_cx}" y="{ring_cy + 136}" class="small dim" text-anchor="middle">'
        f'{max(longest - current, 0)} more to beat the record</text>'
    )

    return f"""{svg_open(w, h, f"Activity: {last_year} contributions in the last year, current streak {current} days, longest {longest} days, {total} all-time")}
<defs>
  {accent_defs(t)}
  <linearGradient id="flame" x1="0" y1="1" x2="0" y2="0">
    <stop offset="0" stop-color="#ff4d6d"/><stop offset=".55" stop-color="#ff9f1c"/><stop offset="1" stop-color="#ffd166"/>
  </linearGradient>
  <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#ffd166"/><stop offset=".5" stop-color="#ff9f1c"/><stop offset="1" stop-color="#ff4d6d"/>
  </linearGradient>
  <clipPath id="langbar"><rect x="{bar_x}" y="{y0 + 202}" width="{bar_w}" height="10" rx="5"/></clipPath>
</defs>
<style>{base_css(t)}
  .huge {{ font-size: 58px; font-weight: 800; letter-spacing: -2px; text-anchor: middle; }}
  .badge {{ font-size: 11px; font-weight: 800; letter-spacing: 1.4px; fill: #ffffff; text-anchor: middle; }}
  .ring {{ stroke-dasharray: {circ:.1f}; stroke-dashoffset: {circ * (1 - ratio):.1f}; animation: ring 1.6s cubic-bezier(.2,.8,.2,1) .2s backwards; }}
  .flicker {{ transform-box: fill-box; transform-origin: 50% 100%; animation: flicker 1.8s ease-in-out infinite; }}
  .bar {{ transform-box: fill-box; transform-origin: 50% 100%; animation: rise .9s cubic-bezier(.2,.8,.2,1) backwards; }}
  .today path:last-of-type {{ animation: glow 1.6s ease-in-out infinite; }}
  @keyframes ring {{ from {{ stroke-dashoffset: {circ:.1f}; }} }}
  @keyframes flicker {{ 50% {{ transform: scale(1.06, .94); }} }}
  @keyframes rise {{ from {{ transform: scaleY(0); }} }}
  @keyframes glow {{ 50% {{ fill: #ffd166; }} }}
</style>
{card(w, h, t)}

<!-- 3D calendar -->
<rect x="24" y="24" width="1152" height="480" rx="16" class="tile"/>
{calendar_3d(t, days, today, 152, 132)}
<g text-anchor="end">
  <text x="1148" y="62" class="kicker">CONTRIBUTIONS · LAST 12 MONTHS</text>
  <text x="1148" y="126" class="fade" style="font-size:64px;font-weight:800;letter-spacing:-2px;fill:url(#accent)">{last_year:,}</text>
  <text x="1148" y="154" class="small dim">{fmt_date(today - timedelta(days=365), today)} – {fmt_date(today, today)}</text>
</g>
<g>
  <text x="48" y="372" class="kicker">HIGHLIGHTS</text>
  <text x="48" y="400" class="small dim">best day <tspan class="strong" style="fill:{t['text']}">{year_days.get(best_day, 0)}</tspan> on {fmt_date(best_day, today)}</text>
  <text x="48" y="422" class="small dim">most active on <tspan class="strong" style="fill:{t['text']}">{top_weekday}</tspan></text>
  <text x="48" y="444" class="small dim"><tspan class="strong" style="fill:{t['text']}">{active_days}</tspan> active days out of 365</text>
  <text x="48" y="470" class="small dim">less</text>{scale}<text x="{80 + 5 * 18 + 4}" y="470" class="small dim">more</text>
</g>

<!-- current streak -->
<rect x="24" y="{y0}" width="356" height="316" rx="16" class="tile"/>
<text x="48" y="{y0 + 34}" class="kicker">CURRENT STREAK</text>
<circle cx="{ring_cx}" cy="{ring_cy}" r="{r}" fill="none" stroke="{t['track']}" stroke-width="14"/>
<circle cx="{ring_cx}" cy="{ring_cy}" r="{r}" fill="none" stroke="url(#ringGrad)" stroke-width="14" stroke-linecap="round"
        class="ring" transform="rotate(-90 {ring_cx} {ring_cy})"/>
<g transform="translate({ring_cx} {ring_cy - 40}) scale(.62)">
  <path d="{FLAME}" fill="url(#flame)" class="flicker"/>
  <path d="{FLAME_CORE}" fill="#ffe8a3" class="flicker"/>
</g>
<text x="{ring_cx}" y="{ring_cy + 30}" class="huge fade">{current}</text>
<text x="{ring_cx}" y="{ring_cy + 54}" class="unit fade" text-anchor="middle">{"day" if current == 1 else "days"}</text>
<text x="{ring_cx}" y="{ring_cy + 114}" class="small strong" text-anchor="middle">{fmt_range(cur_start, cur_end, today)}</text>
{badge}

<!-- longest streak -->
<rect x="396" y="{y0}" width="404" height="150" rx="16" class="tile"/>
<text x="420" y="{y0 + 34}" class="kicker">LONGEST STREAK</text>
<text x="420" y="{y0 + 94}" class="big fade" style="animation-delay:.2s">{longest}<tspan class="unit" dx="8">days</tspan></text>
<text x="420" y="{y0 + 126}" class="small dim">{fmt_range(best_start, best_end, today)}</text>

<!-- all-time -->
<rect x="396" y="{y0 + 166}" width="404" height="150" rx="16" class="tile"/>
<text x="420" y="{y0 + 200}" class="kicker">ALL-TIME CONTRIBUTIONS</text>
<text x="420" y="{y0 + 260}" class="big grad fade" style="animation-delay:.35s">{total:,}</text>
<text x="420" y="{y0 + 292}" class="small dim">since {fmt_date(since, today)}</text>

<!-- private + languages -->
<rect x="816" y="{y0}" width="360" height="316" rx="16" class="tile"/>
<text x="840" y="{y0 + 34}" class="kicker">BUILT BEHIND CLOSED DOORS</text>
<text x="840" y="{y0 + 92}" class="big fade" style="animation-delay:.5s">{private_share * 100:.0f}%</text>
<text x="840" y="{y0 + 116}" class="small dim">of last year's contributions are in private repos</text>
<rect x="840" y="{y0 + 130}" width="300" height="8" rx="4" fill="{t['track']}"/>
<rect x="840" y="{y0 + 130}" width="{300 * private_share:.1f}" height="8" rx="4" fill="url(#accent)" class="grow"/>
<text x="840" y="{y0 + 162}" class="small dim"><tspan class="strong" style="fill:{t['text']}">{private_repos}</tspan> of {repo_count} repositories are private</text>
<text x="840" y="{y0 + 190}" class="kicker">TOP LANGUAGES · ALL REPOS</text>
<g clip-path="url(#langbar)"><g class="grow">{''.join(segs)}</g></g>
{''.join(legend)}
</svg>
"""


# ---------------------------------------------------------------- footer

def footer_svg(updated):
    w, h = 1200, 130
    return f"""{svg_open(w, h, "footer")}
<defs>
  <linearGradient id="fbg" x1="0" x2="1">
    <stop offset="0" stop-color="#0a141c"/><stop offset=".55" stop-color="#12303a"/><stop offset="1" stop-color="#1b4654"/>
  </linearGradient>
  <clipPath id="fc"><rect width="{w}" height="{h}" rx="24"/></clipPath>
</defs>
<style>
  text {{ font-family: {FONT}; }}
  .wave {{ animation: wave 12s linear infinite; }}
  .wave2 {{ animation: wave 18s linear infinite reverse; }}
  @keyframes wave {{ to {{ transform: translateX(-1200px); }} }}
</style>
<g clip-path="url(#fc)">
  <rect width="{w}" height="{h}" fill="url(#fbg)"/>
  <g class="wave2" fill="#4cc9f0" fill-opacity=".10">
    <path d="M0 60 Q150 25 300 60 T600 60 T900 60 T1200 60 T1500 60 T1800 60 T2100 60 T2400 60 V130 H0Z"/>
  </g>
  <g class="wave" fill="#2EC4B6" fill-opacity=".16">
    <path d="M0 80 Q150 50 300 80 T600 80 T900 80 T1200 80 T1500 80 T1800 80 T2100 80 T2400 80 V130 H0Z"/>
  </g>
  <text x="600" y="56" text-anchor="middle" style="font-size:20px;font-weight:700;fill:#e6f6f4">Thanks for stopping by</text>
  <text x="600" y="84" text-anchor="middle" style="font-family:{MONO};font-size:12px;fill:#8fb5b0">every card on this page is generated by GitHub Actions · last run {updated}</text>
</g>
</svg>
"""


# ---------------------------------------------------------------- main

def main():
    login, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    now = datetime.now(timezone.utc)
    today = now.date()
    updated = now.strftime("%Y-%m-%d %H:%M UTC")

    user = graphql(PROFILE_QUERY, {"login": login})["user"]
    days = fetch_days(login, user["createdAt"])
    since = date.fromisoformat(user["createdAt"][:10])

    cur, best = streaks(days, today)
    total = sum(days.values())
    collection = user["contributionsCollection"]
    last_year = collection["contributionCalendar"]["totalContributions"]
    private_share = collection["restrictedContributionsCount"] / last_year if last_year else 0
    repos = user["repositories"]["nodes"]
    private_repos = sum(r["isPrivate"] for r in repos)
    print(f"streak {cur[0]} / best {best[0]} / total {total} / private {private_share:.0%}")

    # Featured projects may be forks, which the repository list leaves out
    projects = {name: graphql(REPO_QUERY, {"login": login, "name": name})["repository"] for name, *_ in PROJECTS}

    files = {
        "header.svg": header_svg(login, avatar_data_uri(user["avatarUrl"])),
        "linkedin.svg": linkedin_svg(),
        "footer.svg": footer_svg(updated),
    }
    for theme, t in THEMES.items():
        files[f"about-{theme}.svg"] = about_svg(t, login)
        files[f"stack-{theme}.svg"] = stack_svg(t)
        for name, blurb, tags in PROJECTS:
            files[f"project-{name}-{theme}.svg"] = project_svg(t, projects[name], blurb, tags, now)
        files[f"activity-{theme}.svg"] = activity_svg(
            t, today, since, days, cur, best, total, last_year, private_share,
            private_repos, user["repositories"]["totalCount"], languages(repos),
        )
    for filename, content in files.items():
        with open(os.path.join(out, filename), "w", encoding="utf-8") as f:
            f.write(content)


if __name__ == "__main__":
    main()

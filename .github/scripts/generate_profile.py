"""Generate the profile README visuals from live GitHub data.

Usage: generate_profile.py <username> <out_dir>
Requires GITHUB_TOKEN in the environment (a token that can read private
contributions gives the full picture).

Writes to <out_dir>:
  header.svg, footer.svg              theme-independent hero banners
  stats-dark.svg, stats-light.svg     streaks / totals / languages card
and makes the background of any profile-*.svg (3D graph) transparent.
"""

import base64
import glob
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"

FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace"

STACK = ["Entra ID", "Docker", "Proxmox", "RunPod", "n8n", "Traefik", "ComfyUI", "Linux"]

ROLES = [
    "IT Project Manager · higher education",
    "DevOps · CI/CD · Docker · reverse proxies",
    "Identity & Access · Entra ID · SSO / OIDC",
    "GenAI on serverless GPUs · ComfyUI · RunPod",
]

THEMES = {
    "dark": {
        "bg": "#0d1117", "card": "#111a22", "tile": "#16212b", "border": "#26333f",
        "text": "#e6edf3", "muted": "#8b949e", "track": "#22303c",
        "accent": "#2EC4B6", "accent2": "#4cc9f0",
    },
    "light": {
        "bg": "#ffffff", "card": "#f6f8fa", "tile": "#ffffff", "border": "#d0d7de",
        "text": "#1f2328", "muted": "#59636e", "track": "#e3e8ee",
        "accent": "#0f9488", "accent2": "#0284c7",
    },
}

FLAME = (
    "M0,-34 C10,-22 24,-10 22,8 C20,24 8,32 0,32 C-8,32 -22,24 -22,8 "
    "C-22,-4 -14,-12 -10,-20 C-8,-10 -4,-6 0,-4 C4,-12 4,-22 0,-34 Z"
)
FLAME_CORE = "M0,-6 C6,2 12,8 10,18 C8,26 -8,26 -10,18 C-12,10 -6,4 0,-6 Z"


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
    return payload["data"]["user"]


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    name createdAt avatarUrl(size: 160)
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      totalCount
      nodes {
        isPrivate stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      restrictedContributionsCount
      totalCommitContributions
      contributionCalendar { totalContributions }
    }
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
        user = graphql(CALENDAR_QUERY, {"login": login, "from": start.isoformat(), "to": end.isoformat()})
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


def weekly(days, today, weeks=52):
    return [
        sum(days.get(today - timedelta(days=w * 7 + i), 0) for i in range(7))
        for w in reversed(range(weeks))
    ]


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


def svg_open(width, height, label):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
    )


# ---------------------------------------------------------------- header

def header_svg(name, login, avatar, current, total, since_year, updated):
    w, h = 1200, 320
    cx, cy = 930, 162
    nodes = []
    for i, label in enumerate(STACK):
        angle = -math.pi / 2 + i * 2 * math.pi / len(STACK)
        nodes.append((cx + 205 * math.cos(angle), cy + 112 * math.sin(angle), label))

    links = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" class="link" '
        f'style="animation-delay:{-i * 0.35:.2f}s"/>'
        for i, (x, y, _) in enumerate(nodes)
    )
    ring = "".join(
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{nodes[(i + 1) % len(nodes)][0]:.1f}" '
        f'y2="{nodes[(i + 1) % len(nodes)][1]:.1f}" class="mesh"/>'
        for i, (x, y, _) in enumerate(nodes)
    )
    dots = "".join(
        f'<g class="node" style="animation-delay:{i * 0.4:.1f}s">'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="dot"/>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="halo" style="animation-delay:{i * 0.4:.1f}s"/>'
        f'<text x="{x:.1f}" y="{y + (20 if y >= cy else -12):.1f}" class="nlabel">{escape(label)}</text></g>'
        for i, (x, y, label) in enumerate(nodes)
    )
    roles = "".join(
        f'<text x="64" y="206" class="role" style="animation-delay:{i * 3}s{';opacity:1' if i == 0 else ''}">{escape(r)}</text>'
        for i, r in enumerate(ROLES)
    )
    period = len(ROLES) * 3

    return f"""{svg_open(w, h, f"{name} — {ROLES[0]}")}
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0b1620"/><stop offset=".55" stop-color="#14303b"/><stop offset="1" stop-color="#1d4552"/>
  </linearGradient>
  <linearGradient id="title" x1="0" x2="1">
    <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#9ef0e6"/>
  </linearGradient>
  <radialGradient id="blobA"><stop offset="0" stop-color="#2EC4B6" stop-opacity=".55"/><stop offset="1" stop-color="#2EC4B6" stop-opacity="0"/></radialGradient>
  <radialGradient id="blobB"><stop offset="0" stop-color="#4cc9f0" stop-opacity=".40"/><stop offset="1" stop-color="#4cc9f0" stop-opacity="0"/></radialGradient>
  <radialGradient id="blobC"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".30"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></radialGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
    <path d="M32 0H0V32" fill="none" stroke="#ffffff" stroke-opacity=".045"/>
  </pattern>
  <clipPath id="card"><rect width="{w}" height="{h}" rx="24"/></clipPath>
  <clipPath id="avatar"><circle cx="{cx}" cy="{cy}" r="42"/></clipPath>
</defs>
<style>
  text {{ font-family: {FONT}; }}
  .mono {{ font-family: {MONO}; }}
  .prompt {{ font-size: 15px; fill: #2EC4B6; }}
  .name {{ font-size: 60px; font-weight: 800; letter-spacing: -1px; fill: url(#title); }}
  .role {{ font-size: 21px; fill: #cfe9e6; opacity: 0; animation: role {period}s infinite; }}
  .chip {{ font-family: {MONO}; font-size: 13px; fill: #cfe9e6; }}
  .link {{ stroke: #2EC4B6; stroke-opacity: .55; stroke-width: 1.4; stroke-dasharray: 3 9; animation: flow 1.6s linear infinite; }}
  .mesh {{ stroke: #ffffff; stroke-opacity: .08; stroke-width: 1; }}
  .dot {{ fill: #9ef0e6; }}
  .halo {{ fill: none; stroke: #2EC4B6; stroke-width: 2; transform-box: fill-box; transform-origin: center; animation: ping 3.2s ease-out infinite; }}
  .nlabel {{ font-family: {MONO}; font-size: 12px; fill: #b7d6d2; text-anchor: middle; }}
  .live {{ fill: #3fb950; animation: blink 1.6s ease-in-out infinite; }}
  .orbit {{ fill: none; stroke: #2EC4B6; stroke-opacity: .5; stroke-width: 2; stroke-dasharray: 6 10; transform-origin: {cx}px {cy}px; animation: spin 18s linear infinite; }}
  @keyframes role {{ 0% {{ opacity: 0; }} 3% {{ opacity: 1; }} 22% {{ opacity: 1; }} 25% {{ opacity: 0; }} 100% {{ opacity: 0; }} }}
  @keyframes flow {{ to {{ stroke-dashoffset: -24; }} }}
  @keyframes ping {{ 0% {{ transform: scale(1); opacity: .9; }} 80%, 100% {{ transform: scale(3.2); opacity: 0; }} }}
  @keyframes blink {{ 50% {{ opacity: .35; }} }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
<g clip-path="url(#card)">
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" fill="url(#grid)"/>
  <circle cx="180" cy="40" r="260" fill="url(#blobA)">
    <animate attributeName="cx" values="180;320;180" dur="14s" repeatCount="indefinite"/>
  </circle>
  <circle cx="1000" cy="300" r="300" fill="url(#blobB)">
    <animate attributeName="cy" values="300;200;300" dur="11s" repeatCount="indefinite"/>
  </circle>
  <circle cx="620" cy="-40" r="220" fill="url(#blobC)">
    <animate attributeName="cx" values="620;520;620" dur="16s" repeatCount="indefinite"/>
  </circle>

  <text x="64" y="84" class="mono prompt">~/{escape(login)} $ whoami</text>
  <text x="62" y="152" class="name">{escape(name)}</text>
  {roles}

  <g transform="translate(64 240)">
    <rect width="470" height="34" rx="17" fill="#ffffff" fill-opacity=".07" stroke="#2EC4B6" stroke-opacity=".35"/>
    <circle cx="20" cy="17" r="5" class="live"/>
    <text x="34" y="22" class="chip">{current}-day streak · {total:,} contributions since {since_year}</text>
  </g>

  {ring}
  {links}
  {dots}
  <circle cx="{cx}" cy="{cy}" r="56" class="orbit"/>
  <circle cx="{cx}" cy="{cy}" r="46" fill="#0b1620" stroke="#2EC4B6" stroke-width="2"/>
  <image href="{avatar}" x="{cx - 42}" y="{cy - 42}" width="84" height="84" clip-path="url(#avatar)" preserveAspectRatio="xMidYMid slice"/>
  <text x="{w - 24}" y="{h - 18}" class="mono nlabel" style="text-anchor:end;fill:#6f8f8b">refreshed {updated}</text>
</g>
</svg>
"""


# ---------------------------------------------------------------- stats card

def stats_svg(t, today, since, cur, best, total, last_year, private_share, private_repos, repo_count, langs, weeks):
    w, h = 1200, 470
    current, cur_start, cur_end = cur
    longest, best_start, best_end = best
    ratio = 1 if longest == 0 else min(current / longest, 1)
    is_best = current > 0 and current >= longest

    # Ring
    r = 84
    circ = 2 * math.pi * r
    ring_cx, ring_cy = 202, 186

    # Language bar
    bar_x, bar_w = 824, 316
    segs, legend, x = [], [], bar_x
    for i, (lang, share, color) in enumerate(langs):
        seg_w = share * bar_w
        segs.append(f'<rect x="{x:.1f}" y="226" width="{max(seg_w, 0.5):.1f}" height="10" fill="{color}"/>')
        x += seg_w
        lx = bar_x + (i % 2) * 168
        ly = 262 + (i // 2) * 22
        legend.append(
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 16}" y="{ly}" class="small">{escape(lang)} '
            f'<tspan class="dim">{share * 100:.1f}%</tspan></text>'
        )

    # 52-week activity
    sp_x, sp_y, sp_w, sp_h = 64, 380, 1072, 58
    peak = max(weeks) or 1
    step = sp_w / (len(weeks) - 1)
    pts = [(sp_x + i * step, sp_y + sp_h - v / peak * sp_h) for i, v in enumerate(weeks)]
    line = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    area = f"{line} L{sp_x + sp_w:.1f},{sp_y + sp_h} L{sp_x},{sp_y + sp_h} Z"
    peak_i = weeks.index(max(weeks))
    peak_x, peak_y = pts[peak_i]
    peak_anchor = "end" if peak_x > sp_x + sp_w - 80 else "middle"

    badge = (
        f'<g class="fade" style="animation-delay:.9s"><rect x="{ring_cx - 58}" y="{ring_cy + 122}" width="116" height="22" rx="11" '
        f'fill="url(#flame)"/><text x="{ring_cx}" y="{ring_cy + 137}" class="badge">PERSONAL BEST</text></g>'
        if is_best else
        f'<text x="{ring_cx}" y="{ring_cy + 136}" class="small dim" text-anchor="middle">'
        f'{max(longest - current, 0)} more to beat the record</text>'
    )

    return f"""{svg_open(w, h, f"Current streak {current} days, longest {longest} days, {total} contributions")}
<defs>
  <linearGradient id="flame" x1="0" y1="1" x2="0" y2="0">
    <stop offset="0" stop-color="#ff4d6d"/><stop offset=".55" stop-color="#ff9f1c"/><stop offset="1" stop-color="#ffd166"/>
  </linearGradient>
  <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#ffd166"/><stop offset=".5" stop-color="#ff9f1c"/><stop offset="1" stop-color="#ff4d6d"/>
  </linearGradient>
  <linearGradient id="accent" x1="0" x2="1">
    <stop offset="0" stop-color="{t['accent']}"/><stop offset="1" stop-color="{t['accent2']}"/>
  </linearGradient>
  <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{t['accent']}" stop-opacity=".45"/><stop offset="1" stop-color="{t['accent']}" stop-opacity="0"/>
  </linearGradient>
  <clipPath id="langbar"><rect x="{bar_x}" y="226" width="{bar_w}" height="10" rx="5"/></clipPath>
</defs>
<style>
  text {{ font-family: {FONT}; fill: {t['text']}; }}
  .kicker {{ font-size: 12px; font-weight: 700; letter-spacing: 1.6px; fill: {t['muted']}; }}
  .big {{ font-size: 46px; font-weight: 800; letter-spacing: -1px; }}
  .huge {{ font-size: 58px; font-weight: 800; letter-spacing: -2px; text-anchor: middle; }}
  .unit {{ font-size: 18px; font-weight: 600; fill: {t['muted']}; }}
  .small {{ font-size: 13px; }}
  .dim {{ fill: {t['muted']}; }}
  .badge {{ font-size: 11px; font-weight: 800; letter-spacing: 1.4px; fill: #ffffff; text-anchor: middle; }}
  .tile {{ fill: {t['tile']}; stroke: {t['border']}; }}
  .grad {{ fill: url(#accent); }}
  /* Final state is the default; animations start from the hidden state so
     static renderers still show everything */
  .fade {{ animation: fade .8s ease-out backwards; }}
  .ring {{ stroke-dasharray: {circ:.1f}; stroke-dashoffset: {circ * (1 - ratio):.1f}; animation: ring 1.6s cubic-bezier(.2,.8,.2,1) .2s backwards; }}
  .flicker {{ transform-box: fill-box; transform-origin: 50% 100%; animation: flicker 1.8s ease-in-out infinite; }}
  .grow {{ transform-box: fill-box; transform-origin: left; animation: grow 1.2s cubic-bezier(.2,.8,.2,1) .4s backwards; }}
  .draw {{ stroke-dasharray: 1; animation: draw 2s ease-out .3s backwards; }}
  @keyframes fade {{ from {{ opacity: 0; }} }}
  @keyframes ring {{ from {{ stroke-dashoffset: {circ:.1f}; }} }}
  @keyframes flicker {{ 50% {{ transform: scale(1.06, .94); }} }}
  @keyframes grow {{ from {{ transform: scaleX(0); }} }}
  @keyframes draw {{ from {{ stroke-dashoffset: 1; }} }}
</style>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20" fill="{t['card']}" stroke="{t['border']}"/>

<!-- current streak -->
<rect x="24" y="24" width="356" height="310" rx="16" class="tile"/>
<text x="48" y="58" class="kicker">CURRENT STREAK</text>
<circle cx="{ring_cx}" cy="{ring_cy}" r="{r}" fill="none" stroke="{t['track']}" stroke-width="14"/>
<circle cx="{ring_cx}" cy="{ring_cy}" r="{r}" fill="none" stroke="url(#ringGrad)" stroke-width="14" stroke-linecap="round"
        class="ring" transform="rotate(-90 {ring_cx} {ring_cy})"/>
<g transform="translate({ring_cx} {ring_cy - 40}) scale(.62)">
  <path d="{FLAME}" fill="url(#flame)" class="flicker"/>
  <path d="{FLAME_CORE}" fill="#ffe8a3" class="flicker"/>
</g>
<text x="{ring_cx}" y="{ring_cy + 30}" class="huge fade">{current}</text>
<text x="{ring_cx}" y="{ring_cy + 54}" class="unit fade" text-anchor="middle">{"day" if current == 1 else "days"}</text>
<text x="{ring_cx}" y="{ring_cy + 114}" class="small" text-anchor="middle" style="font-weight:600">{fmt_range(cur_start, cur_end, today)}</text>
{badge}

<!-- longest streak -->
<rect x="396" y="24" width="400" height="147" rx="16" class="tile"/>
<text x="420" y="58" class="kicker">LONGEST STREAK</text>
<text x="420" y="116" class="big fade" style="animation-delay:.2s">{longest}<tspan class="unit" dx="8">days</tspan></text>
<text x="420" y="148" class="small dim">{fmt_range(best_start, best_end, today)}</text>

<!-- all-time -->
<rect x="396" y="187" width="400" height="147" rx="16" class="tile"/>
<text x="420" y="221" class="kicker">ALL-TIME CONTRIBUTIONS</text>
<text x="420" y="279" class="big grad fade" style="animation-delay:.35s">{total:,}</text>
<text x="420" y="311" class="small dim">since {fmt_date(since, today)} · <tspan style="fill:{t['text']};font-weight:700">{last_year:,}</tspan> in the last 12 months</text>

<!-- private + languages -->
<rect x="812" y="24" width="364" height="310" rx="16" class="tile"/>
<text x="836" y="58" class="kicker">BUILT BEHIND CLOSED DOORS</text>
<text x="836" y="116" class="big fade" style="animation-delay:.5s">{private_share * 100:.0f}%</text>
<text x="836" y="140" class="small dim">of last year's contributions are in private repos</text>
<rect x="836" y="154" width="304" height="8" rx="4" fill="{t['track']}"/>
<rect x="836" y="154" width="{304 * private_share:.1f}" height="8" rx="4" fill="url(#accent)" class="grow"/>
<text x="836" y="186" class="small dim"><tspan style="fill:{t['text']};font-weight:700">{private_repos}</tspan> of {repo_count} repositories are private</text>
<text x="836" y="214" class="kicker">TOP LANGUAGES · ALL REPOS</text>
<g clip-path="url(#langbar)"><g class="grow">{''.join(segs)}</g></g>
{''.join(legend)}

<!-- 52 weeks -->
<rect x="24" y="350" width="1152" height="96" rx="16" class="tile"/>
<text x="48" y="374" class="kicker">LAST 52 WEEKS</text>
<path d="{area}" fill="url(#area)" class="fade" style="animation-delay:.6s"/>
<path d="{line}" fill="none" stroke="url(#accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" pathLength="1" class="draw"/>
<circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="4.5" fill="{t['accent']}" class="fade" style="animation-delay:1.6s"/>
<text x="{peak_x:.1f}" y="{peak_y - 10:.1f}" class="small fade" text-anchor="{peak_anchor}" style="animation-delay:1.6s;font-weight:700">peak · {max(weeks)}/week</text>
</svg>
"""


# ---------------------------------------------------------------- footer

def footer_svg(updated):
    w, h = 1200, 150
    return f"""{svg_open(w, h, "footer")}
<defs>
  <linearGradient id="fbg" x1="0" x2="1">
    <stop offset="0" stop-color="#0b1620"/><stop offset=".55" stop-color="#14303b"/><stop offset="1" stop-color="#1d4552"/>
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
    <path d="M0 70 Q150 30 300 70 T600 70 T900 70 T1200 70 T1500 70 T1800 70 T2100 70 T2400 70 V150 H0Z"/>
  </g>
  <g class="wave" fill="#2EC4B6" fill-opacity=".16">
    <path d="M0 90 Q150 60 300 90 T600 90 T900 90 T1200 90 T1500 90 T1800 90 T2100 90 T2400 90 V150 H0Z"/>
  </g>
  <text x="600" y="62" text-anchor="middle" style="font-size:20px;font-weight:700;fill:#e6f6f4">Thanks for stopping by — most of the good stuff is private 🔒</text>
  <text x="600" y="92" text-anchor="middle" style="font-family:{MONO};font-size:12px;fill:#8fb5b0">generated by GitHub Actions every 12 h · last run {updated}</text>
</g>
</svg>
"""


# ---------------------------------------------------------------- 3D graph

def make_transparent(path):
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    if ".fill-bg { fill: none; }" not in svg:
        # Later CSS rule wins: hide the full-size background rect
        svg = svg.replace("</style>", "\n.fill-bg { fill: none; }</style>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


# ---------------------------------------------------------------- main

def main():
    login, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    now = datetime.now(timezone.utc)
    today = now.date()
    updated = now.strftime("%Y-%m-%d %H:%M UTC")

    user = graphql(PROFILE_QUERY, {"login": login})
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

    name = user["name"] or login
    if os.environ.get("PROFILE_NAME"):
        name = os.environ["PROFILE_NAME"]

    files = {
        "header.svg": header_svg(name, login, avatar_data_uri(user["avatarUrl"]), cur[0], total, since.year, updated),
        "footer.svg": footer_svg(updated),
    }
    for theme, colors in THEMES.items():
        files[f"stats-{theme}.svg"] = stats_svg(
            colors, today, since, cur, best, total, last_year, private_share,
            private_repos, user["repositories"]["totalCount"], languages(repos), weekly(days, today),
        )
    for filename, content in files.items():
        with open(os.path.join(out, filename), "w", encoding="utf-8") as f:
            f.write(content)

    for path in glob.glob(os.path.join(out, "profile-*.svg")):
        make_transparent(path)


if __name__ == "__main__":
    main()

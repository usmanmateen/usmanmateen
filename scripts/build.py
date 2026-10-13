"""Build the profile README's images and pull-request tables from the GitHub API.

Writes assets/{header,open-source,activity}-{light,dark}.svg in the design of
usmanmateen.com (canvas, indigo and teal, Space Grotesk / Inter / JetBrains Mono /
Instrument Serif, embedded as subsets) and refreshes the generated blocks in
README.md. Needs a token in GITHUB_TOKEN (or GH_TOKEN), plus fonttools and brotli.

    GITHUB_TOKEN=... python scripts/build.py
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import os
import re
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
USER = "usmanmateen"

# Short labels for the logo wall.
SHORT = {"lm-evaluation-harness": "lm-eval", "msoffcrypto-tool": "msoffcrypto", "openvino": "OpenVINO", "vllm": "vLLM",
         "docling": "Docling", "presidio": "Presidio", "pypdf": "pypdf", "unstructured": "Unstructured", "dspy": "DSPy",
         "DeepSpeed": "DeepSpeed", "coremltools": "coremltools", "Curator": "NeMo Curator"}

# Closed pull requests are left out unless they have a note here (same rule as the site).
NOTES = {
    "docling-project/docling#4681": "Superseded by #4683, which has the same fix plus MHTML support.",
}

THEMES = {
    "light": {
        "bg": "#fbfbfe", "surface": "#ffffff", "line": "rgba(23,23,42,0.10)", "grid": "rgba(99,102,241,0.05)",
        "text": "#16161d", "muted": "#585b6b", "dim": "#6b6e7c",
        "acc": "#6366f1", "acc_ink": "#4f46e5", "acc_soft": "#eef0ff", "sig": "#0f9d8f", "sig_ink": "#0b7a70",
        "merged": "#8250df", "open": "#1a7f37",
        "mesh": ["#c5cafc", "#fbc7e6", "#bfe0ff", "#b9f4e6"], "mesh_opacity": 0.55,
        "heat": ["#eceef6", "#c7cbfb", "#9aa1f6", "#6366f1", "#4338ca"],
    },
    "dark": {
        "bg": "#0f1117", "surface": "#161925", "line": "rgba(232,233,242,0.12)", "grid": "rgba(129,140,248,0.06)",
        "text": "#ececf4", "muted": "#a3a6b8", "dim": "#9497aa",
        "acc": "#818cf8", "acc_ink": "#a5b4fc", "acc_soft": "#1e2140", "sig": "#2dd4bf", "sig_ink": "#5eead4",
        "merged": "#a371f7", "open": "#3fb950",
        "mesh": ["#3b3f8f", "#6b2f5f", "#1f4a70", "#145a50"], "mesh_opacity": 0.45,
        "heat": ["#1b1e2b", "#2f3474", "#4549b8", "#6366f1", "#a5b4fc"],
    },
}

FONT_FILES = {
    "Space Grotesk": "Space_Grotesk-300_700-normal.woff2",
    "Inter": "Inter-100_900-normal.woff2",
    "JetBrains Mono": "JetBrains_Mono-100_800-normal.woff2",
    "Instrument Serif": "Instrument_Serif-400-italic.woff2",
}


# ── GitHub ──────────────────────────────────────────────────────────────────

def graphql(query: str, **variables) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


PRS = """query($q: String!) {
  search(query: $q, type: ISSUE, first: 100) {
    nodes { ... on PullRequest {
      title url number state merged mergedAt createdAt closedAt isInMergeQueue reviewDecision additions deletions
      repository { nameWithOwner url stargazerCount isPrivate owner { __typename login avatarUrl } }
    } }
  }
}"""

CALENDAR = """query($login: String!) {
  user(login: $login) { contributionsCollection { contributionCalendar {
    totalContributions weeks { contributionDays { date contributionCount } }
  } } }
}"""


def pull_requests() -> list[dict]:
    nodes = graphql(PRS, q=f"is:pr author:{USER} -user:{USER}")["search"]["nodes"]
    prs = []
    for n in nodes:
        repo = n.get("repository") or {}
        if not n or repo.get("isPrivate"):
            continue
        key = f"{repo['nameWithOwner']}#{n['number']}"
        if n["merged"]:
            status = "merged"
        elif n["state"] == "OPEN":
            status = "queued" if n["isInMergeQueue"] else "approved" if n["reviewDecision"] == "APPROVED" else "review"
        elif key in NOTES:
            status = "superseded"
        else:
            continue
        prs.append({**n, "status": status, "key": key})
    order = {"merged": 0, "queued": 1, "approved": 2, "review": 3, "superseded": 4}
    prs.sort(key=lambda p: (order[p["status"]], -(p["repository"]["stargazerCount"]), p["key"]))
    return prs


def calendar() -> dict:
    return graphql(CALENDAR, login=USER)["user"]["contributionsCollection"]["contributionCalendar"]


def data_uri(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as resp:
        body, kind = resp.read(), resp.headers.get_content_type()
    return f"data:{kind};base64,{base64.b64encode(body).decode()}"


# ── SVG helpers ─────────────────────────────────────────────────────────────

def font_faces(svg_text: str, families: list[str]) -> str:
    """@font-face rules with each family subset to the characters the SVG uses."""
    chars = set(html.unescape(re.sub(r"<[^>]+>", " ", svg_text))) | set(" .,·")
    rules = []
    for family in families:
        font = TTFont(ASSETS / "fonts" / FONT_FILES[family])
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        sub = subset.Subsetter(options)
        sub.populate(text="".join(chars))
        sub.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff2"
        font.save(buf)
        style = "italic" if family == "Instrument Serif" else "normal"
        weight = "400" if family == "Instrument Serif" else "100 900"
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{base64.b64encode(buf.getvalue()).decode()}) format('woff2');}}"
        )
    return "".join(rules)


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def svg(width: int, height: int, body: str, t: dict, title: str, families: list[str]) -> str:
    inner = (
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="18" fill="{t["bg"]}" stroke="{t["line"]}" stroke-width="2"/>'
        + body
    )
    fonts = font_faces(inner, families)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>'
        f"<style>{fonts}"
        ".d{font-family:'Space Grotesk',sans-serif}.b{font-family:'Inter',sans-serif}"
        ".m{font-family:'JetBrains Mono',monospace}.s{font-family:'Instrument Serif',serif;font-style:italic}"
        f"</style>{inner}</svg>"
    )


def grid(width: int, height: int, t: dict, step: int = 40) -> str:
    lines = [f'<path d="M{x} 2V{height - 2}" stroke="{t["grid"]}"/>' for x in range(step, width, step)]
    lines += [f'<path d="M2 {y}H{width - 2}" stroke="{t["grid"]}"/>' for y in range(step, height, step)]
    return f'<g clip-path="url(#clip)">{"".join(lines)}</g>'


def clip(width: int, height: int) -> str:
    return f'<clipPath id="clip"><rect x="2" y="2" width="{width - 4}" height="{height - 4}" rx="17"/></clipPath>'


# ── Images ──────────────────────────────────────────────────────────────────

def header(t: dict, counts: dict) -> str:
    w, h = 1200, 300
    blobs = "".join(
        f'<radialGradient id="g{i}"><stop offset="0" stop-color="{c}" stop-opacity="{t["mesh_opacity"]}"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
        for i, c in enumerate(t["mesh"])
    )
    mesh = (
        f'<g clip-path="url(#clip)"><ellipse cx="1060" cy="40" rx="420" ry="260" fill="url(#g0)"/>'
        f'<ellipse cx="760" cy="300" rx="380" ry="200" fill="url(#g1)"/>'
        f'<ellipse cx="120" cy="10" rx="360" ry="220" fill="url(#g2)"/>'
        f'<ellipse cx="300" cy="320" rx="420" ry="180" fill="url(#g3)"/></g>'
    )
    card_x, card_y = 820, 62
    receipt = (
        f'<rect x="{card_x}" y="{card_y}" width="320" height="176" rx="16" fill="{t["surface"]}" stroke="{t["line"]}" stroke-width="2"/>'
        f'<text x="{card_x + 24}" y="{card_y + 38}" class="m" font-size="14" font-weight="600" letter-spacing="2" fill="{t["acc_ink"]}">OPEN SOURCE</text>'
        f'<text x="{card_x + 24}" y="{card_y + 92}" class="d" font-size="46" font-weight="700" fill="{t["merged"]}">{counts["merged"]}'
        f'<tspan class="b" font-size="20" font-weight="600" fill="{t["muted"]}" dx="10">merged</tspan></text>'
        f'<text x="{card_x + 24}" y="{card_y + 130}" class="b" font-size="18" font-weight="600" fill="{t["text"]}">'
        f'{counts["review"] + counts["approved"] + counts["queued"]} in review · {counts["projects"]} projects</text>'
        f'<text x="{card_x + 24}" y="{card_y + 156}" class="m" font-size="13" fill="{t["dim"]}">updated {counts["date"]}</text>'
    )
    body = (
        f"<defs>{clip(w, h)}{blobs}</defs>{mesh}{grid(w, h, t)}"
        f'<text x="64" y="86" class="m" font-size="15" font-weight="600" letter-spacing="3" fill="{t["acc_ink"]}">AI ENGINEER · BIRMINGHAM, UK</text>'
        f'<text x="62" y="152" class="d" font-size="58" font-weight="700" letter-spacing="-1.6" fill="{t["text"]}">Muhammad Usman Mateen</text>'
        f'<text x="64" y="200" class="s" font-size="34" fill="{t["muted"]}">I build and ship production AI and automation.</text>'
        f'<rect x="64" y="226" width="474" height="36" rx="18" fill="{t["surface"]}" stroke="{t["line"]}" stroke-width="2"/>'
        f'<circle cx="86" cy="244" r="6" fill="{t["sig"]}"/>'
        f'<text x="102" y="250" class="b" font-size="15" font-weight="600" fill="{t["sig_ink"]}">Open to mid-level AI / applied-AI / automation roles</text>'
        + receipt
    )
    return svg(w, h, body, t, "Muhammad Usman Mateen, AI Engineer. I build and ship production AI and automation.",
               ["Space Grotesk", "Inter", "JetBrains Mono", "Instrument Serif"])


def open_source(t: dict, prs: list[dict], avatars: dict, counts: dict) -> str:
    w = 1200
    # One tile per organisation, merged first, then by stars.
    orgs: dict[str, dict] = {}
    for p in prs:
        owner = p["repository"]["owner"]["login"]
        o = orgs.setdefault(owner, {"owner": owner, "merged": False, "stars": 0, "repos": set(),
                                    "person": p["repository"]["owner"]["__typename"] == "User"})
        o["merged"] |= p["status"] == "merged"
        o["stars"] = max(o["stars"], p["repository"]["stargazerCount"])
        o["repos"].add(p["repository"]["nameWithOwner"].split("/")[1])
    tiles = sorted(orgs.values(), key=lambda o: (not o["merged"], -o["stars"]))
    per_row, size, gap = 9, 96, 30
    rows = (len(tiles) + per_row - 1) // per_row
    h = 236 + rows * (size + 58) + 40
    stats = [
        (str(counts["merged"]), "merged", t["merged"]),
        (str(counts["review"] + counts["approved"] + counts["queued"]), "open or in review", t["open"]),
        (str(counts["projects"]), "projects", t["acc_ink"]),
        (f"{counts['stars'] // 1000}k+", "stars across these repos", t["text"]),
    ]
    stat_svg = ""
    for i, (v, label, color) in enumerate(stats):
        x = 48 + i * 280
        stat_svg += (
            f'<rect x="{x}" y="86" width="256" height="112" rx="14" fill="{t["surface"]}" stroke="{t["line"]}" stroke-width="2"/>'
            f'<text x="{x + 22}" y="146" class="d" font-size="48" font-weight="700" letter-spacing="-1" fill="{color}">{esc(v)}</text>'
            f'<text x="{x + 22}" y="178" class="b" font-size="16" font-weight="600" fill="{t["muted"]}">{esc(label)}</text>'
        )
    tile_svg = ""
    row_w = per_row * size + (per_row - 1) * gap
    for i, o in enumerate(tiles):
        r, c = divmod(i, per_row)
        n_in_row = min(per_row, len(tiles) - r * per_row)
        x0 = (w - (n_in_row * size + (n_in_row - 1) * gap)) / 2 if n_in_row < per_row else (w - row_w) / 2
        x = x0 + c * (size + gap)
        y = 236 + r * (size + 58)
        ring = (f'<rect x="{x - 6}" y="{y - 6}" width="{size + 12}" height="{size + 12}" rx="28" fill="none" '
                f'stroke="{t["merged"]}" stroke-width="4"/>' if o["merged"] else "")
        repo = sorted(o["repos"])[0]
        label = SHORT.get(repo, repo) if len(o["repos"]) == 1 else o["owner"].capitalize() if o["owner"].islower() else o["owner"]
        if o["owner"] == "pytorch":
            label = "PyTorch"
        tile_svg += (
            f'<clipPath id="t{i}"><rect x="{x}" y="{y}" width="{size}" height="{size}" rx="22"/></clipPath>'
            f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="22" fill="#ffffff" stroke="{t["line"]}" stroke-width="2"/>'
            + (f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="22" fill="{t["acc_soft"]}"/>'
               f'<text x="{x + size / 2}" y="{y + size / 2 + 13}" text-anchor="middle" class="d" font-size="36" font-weight="700" '
               f'fill="{t["acc_ink"]}">{esc(label[:2].upper())}</text>'
               if o["person"] else
               f'<image href="{avatars[o["owner"]]}" x="{x}" y="{y}" width="{size}" height="{size}" clip-path="url(#t{i})"/>')
            + f'{ring}'
            f'<text x="{x + size / 2}" y="{y + size + 30}" text-anchor="middle" class="m" font-size="13" fill="{t["text"]}">{esc(label[:16])}</text>'
        )
    legend_y = h - 34
    body = (
        f"<defs>{clip(w, h)}</defs>{grid(w, h, t)}"
        f'<text x="48" y="58" class="m" font-size="15" font-weight="600" letter-spacing="3" fill="{t["acc_ink"]}">PULL REQUESTS TO OTHER PEOPLE\'S PROJECTS</text>'
        + stat_svg + tile_svg
        + f'<rect x="{w / 2 - 150}" y="{legend_y - 14}" width="18" height="18" rx="5" fill="none" stroke="{t["merged"]}" stroke-width="3"/>'
        f'<text x="{w / 2 - 124}" y="{legend_y}" class="b" font-size="15" fill="{t["muted"]}">merged</text>'
        f'<rect x="{w / 2 - 40}" y="{legend_y - 14}" width="18" height="18" rx="5" fill="none" stroke="{t["line"]}" stroke-width="2"/>'
        f'<text x="{w / 2 - 14}" y="{legend_y}" class="b" font-size="15" fill="{t["muted"]}">open or in review</text>'
    )
    return svg(w, h, body, t, f"Open source: {counts['merged']} merged pull requests, {counts['review']} in review.",
               ["Space Grotesk", "Inter", "JetBrains Mono"])


def activity(t: dict, cal: dict) -> str:
    days = [d for wk in cal["weeks"] for d in wk["contributionDays"]]
    counts = sorted(d["contributionCount"] for d in days if d["contributionCount"] > 0)
    def level(n: int) -> int:
        if n == 0 or not counts:
            return 0
        q = [counts[int(len(counts) * f)] for f in (0.25, 0.5, 0.75)]
        return 1 + sum(n > x for x in q)
    cell, gap = 15, 4
    w = 48 + len(cal["weeks"]) * (cell + gap) + 30
    h = 230
    cells = ""
    months = ""
    last_month = None
    for i, wk in enumerate(cal["weeks"]):
        x = 48 + i * (cell + gap)
        for d in wk["contributionDays"]:
            wd = (dt.date.fromisoformat(d["date"]).weekday() + 1) % 7  # Sunday first, like GitHub
            y = 92 + wd * (cell + gap)
            cells += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="4" fill="{t["heat"][level(d["contributionCount"])]}"/>'
        month = dt.date.fromisoformat(wk["contributionDays"][0]["date"]).strftime("%b")
        if month != last_month and i < len(cal["weeks"]) - 2:
            months += f'<text x="{x}" y="80" class="m" font-size="12" fill="{t["dim"]}">{month}</text>'
            last_month = month
    body = (
        f"<defs>{clip(w, h)}</defs>"
        f'<text x="48" y="48" class="m" font-size="15" font-weight="600" letter-spacing="3" fill="{t["acc_ink"]}">ACTIVITY</text>'
        f'<text x="{w - 30}" y="48" text-anchor="end" class="b" font-size="16" font-weight="600" fill="{t["text"]}">'
        f'{cal["totalContributions"]:,} contributions in the last year</text>'
        + months + cells
    )
    return svg(w, h, body, t, f"{cal['totalContributions']} contributions in the last year.", ["Inter", "JetBrains Mono"])


# ── Hero cards (the workbench from usmanmateen.com) ──────────────────────────

BARCODE = [2, 1, 1, 3, 1, 2, 1, 1, 2, 3, 1, 1, 2, 1, 3, 1, 1, 2, 2, 1, 1, 3, 1, 2, 1, 3, 1, 1, 2, 1, 2, 1, 3, 1, 1, 2]
INK, MUTED, DIM, PAPER_LINE = "#16161d", "#585b6b", "#6b6e7c", "rgba(23,23,42,0.14)"


def barcode(x: float, y: float, w: float, h: float, color: str) -> str:
    unit = w / (sum(BARCODE) * 1.6)
    out, cx = "", x
    for i, n in enumerate(BARCODE):
        if i % 2 == 0:
            out += f'<rect x="{cx:.1f}" y="{y}" width="{n * unit:.1f}" height="{h}" fill="{color}"/>'
        cx += n * unit * 1.6
    return out


def tilt(x: float, y: float, w: float, h: float, rot: float, inner: str) -> str:
    return f'<g transform="rotate({rot} {x + w / 2} {y + h / 2})" filter="url(#shadow)">{inner}</g>'


def panel(x, y, w, h, fill, stroke=PAPER_LINE, rx=16) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'


def text(x, y, s, cls, size, fill, weight=None, anchor=None, spacing=None) -> str:
    attrs = f'x="{x}" y="{y}" class="{cls}" font-size="{size}" fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    if spacing:
        attrs += f' letter-spacing="{spacing}"'
    return f"<text {attrs}>{esc(s)}</text>"


def id_badge(photo: str) -> str:
    x, y, w, h = 56, 104, 250, 316
    strap = (f'<rect x="{x + 106}" y="-20" width="38" height="{y + 2}" fill="#6366f1"/>'
             f'<rect x="{x + 101}" y="{y - 22}" width="48" height="26" rx="6" fill="#9aa0b5"/>')
    inner = (panel(x, y, w, h, "#ffffff")
             + f'<path d="M{x} {y + 16}a16 16 0 0 1 16-16h{w - 32}a16 16 0 0 1 16 16v38h-{w}z" fill="#6366f1"/>'
             + text(x + 18, y + 34, "DEVELOPER ID", "m", 13, "#ffffff", 700, spacing=2)
             + text(x + w - 18, y + 35, "UM.", "d", 17, "#ffffff", 700, anchor="end")
             + f'<clipPath id="ph"><rect x="{x + 18}" y="{y + 72}" width="104" height="120" rx="10"/></clipPath>'
             + f'<image href="{photo}" x="{x + 18}" y="{y + 72}" width="104" height="120" preserveAspectRatio="xMidYMid slice" clip-path="url(#ph)"/>'
             + text(x + 136, y + 92, "Usman", "d", 20, INK, 700)
             + text(x + 136, y + 115, "Mateen", "d", 20, INK, 700)
             + text(x + 136, y + 138, "AI ENGINEER", "m", 12, "#4f46e5", 700, spacing=1.5)
             + text(x + 136, y + 160, "LLM · RAG ·", "b", 12.5, MUTED)
             + text(x + 136, y + 194, "systems", "b", 12.5, MUTED)
             + text(x + 136, y + 177, "Production", "b", 12.5, MUTED)
             + f'<circle cx="{x + 24}" cy="{y + 215}" r="4.5" fill="#10b981"/>'
             + text(x + 36, y + 220, "Birmingham, UK", "m", 12.5, MUTED)
             + barcode(x + 18, y + 238, 214, 36, INK)
             + text(x + w / 2, y + 296, "USMANMATEEN.COM", "m", 11, DIM, anchor="middle", spacing=2))
    return f'<g transform="rotate(-4 {x + w / 2} {y + h / 2})">{strap}<g filter="url(#shadow)">{inner}</g></g>'


def education() -> str:
    x, y, w, h = 344, 60, 290, 192
    inner = (panel(x, y, w, h, "#ffffff")
             + text(x + 20, y + 32, "EDUCATION", "m", 12, DIM, 600, spacing=2)
             + text(x + 20, y + 62, "MSc Applied AI", "d", 19, INK, 700)
             + text(x + 20, y + 82, "Warwick (WMG) · awaiting results", "m", 12, MUTED)
             + text(x + 20, y + 114, "BSc CS with AI · First-Class", "d", 19, INK, 700)
             + text(x + 20, y + 134, "Coventry University", "m", 12, MUTED)
             + f'<path d="M{x + 20} {y + 150}H{x + w - 20}" stroke="{PAPER_LINE}"/>'
             + text(x + 20, y + 174, "EN · UR · PT (spoken)", "m", 12, DIM))
    return tilt(x, y, w, h, 1.5, inner)


def receipt(prs: list[dict], counts: dict) -> str:
    x, y, w, h = 668, 34, 250, 366
    merged = [p for p in prs if p["status"] == "merged"]
    latest = sorted(merged, key=lambda p: p["mergedAt"], reverse=True)[:4]
    teeth = "".join(f"L{x + w - 10 * (k + 1) + 5} {y + h + (6 if k % 2 == 0 else 0)}" for k in range(25))
    body = (f'<path d="M{x} {y}H{x + w}V{y + h}{teeth}L{x} {y + h}Z" fill="#fffdf8" stroke="{PAPER_LINE}" stroke-width="2"/>'
            + text(x + w / 2, y + 46, "OPEN SOURCE", "d", 27, INK, 700, anchor="middle")
            + text(x + w / 2, y + 68, "PULL REQUESTS", "m", 11, DIM, anchor="middle", spacing=2)
            + text(x + w / 2, y + 88, f"@usmanmateen · {counts['date']}", "m", 11, DIM, anchor="middle")
            + f'<path d="M{x + 18} {y + 104}H{x + w - 18}" stroke="#9aa0b5" stroke-dasharray="4 4"/>')
    for i, p in enumerate(latest):
        name = p["repository"]["nameWithOwner"].split("/")[1]
        name = {"msoffcrypto-tool": "msoffcrypto"}.get(name, name)
        yy = y + 130 + i * 22
        body += text(x + 20, yy, f"{name} #{p['number']}", "m", 12.5, INK)
        body += text(x + w - 20, yy, "MERGED", "m", 12, "#8250df", 700, anchor="end")
    sy = y + 130 + len(latest) * 22 + 2
    adds = sum(p["additions"] for p in merged)
    dels = sum(p["deletions"] for p in merged)
    open_n = counts["review"] + counts["approved"] + counts["queued"]
    body += (f'<path d="M{x + 18} {sy}H{x + w - 18}" stroke="#9aa0b5" stroke-dasharray="4 4"/>'
             + text(x + 20, sy + 22, "LINES", "m", 12.5, INK)
             + f'<text x="{x + w - 20}" y="{sy + 22}" text-anchor="end" class="m" font-size="12.5">'
             f'<tspan fill="#1a7f37">+{adds:,}</tspan> <tspan fill="#cf222e">−{dels:,}</tspan></text>'
             + text(x + 20, sy + 42, "MERGED", "m", 12.5, INK)
             + text(x + w - 20, sy + 42, str(counts["merged"]), "m", 12.5, INK, 700, anchor="end")
             + text(x + 20, sy + 62, "IN REVIEW", "m", 12.5, INK)
             + text(x + w - 20, sy + 62, str(open_n), "m", 12.5, INK, 700, anchor="end")
             + barcode(x + 30, y + h - 58, 190, 26, INK)
             + text(x + w / 2, y + h - 14, "thank you for shipping", "s", 16, MUTED, anchor="middle"))
    return tilt(x, y, w, h, -2, body)


def terminal() -> str:
    x, y, w, h = 940, 60, 236, 200
    caret = (f'<rect x="{x + 18}" y="{y + 170}" width="8" height="13" fill="rgba(255,255,255,0.75)">'
             f'<animate attributeName="opacity" values="1;0;1" dur="1.1s" repeatCount="indefinite" calcMode="discrete"/></rect>')
    inner = (panel(x, y, w, h, "#11131a", "rgba(255,255,255,0.10)", rx=14)
             + "".join(f'<circle cx="{x + 20 + k * 16}" cy="{y + 20}" r="5" fill="{c}"/>' for k, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]))
             + text(x + 72, y + 24, "~/research", "m", 11, "rgba(255,255,255,0.45)")
             + text(x + 18, y + 56, "$ dissertation --status", "m", 12.5, "#a5b4fc")
             + text(x + 18, y + 78, "› Hybrid RAG benchmark", "m", 12.5, "#ffffff", 700)
             + text(x + 18, y + 98, "dense · sparse · KG · visual", "m", 12, "rgba(255,255,255,0.62)")
             + text(x + 18, y + 118, "# FinanceBench", "m", 12, "rgba(255,255,255,0.62)")
             + text(x + 18, y + 140, "✓ submitted", "m", 12.5, "#34d399")
             + text(x + 18, y + 160, "awaiting grades", "m", 12, "rgba(255,255,255,0.62)")
             + caret)
    return tilt(x, y, w, h, 2.5, inner)


def music(track: dict) -> str:
    x, y, w, h = 938, 300, 240, 106
    has = bool(track.get("title"))
    label = "Now playing" if track.get("isPlaying") else ("Last played" if has else "Now playing")
    title = track.get("title") if has else "Deep Work"
    artist = track.get("artist") if has else "focus mix · while shipping"
    bars = ""
    for i, (a, b) in enumerate([(5, 9), (10, 4), (6, 11), (9, 5)]):
        dur = f"{0.9 + i * 0.15:.2f}s"
        base = y + 30
        bars += (f'<rect x="{x + 204 + i * 5}" y="{base - a}" width="3" height="{a}" rx="1.5" fill="#6ee7b7">'
                 f'<animate attributeName="height" values="{a};12;{b};{a}" dur="{dur}" repeatCount="indefinite"/>'
                 f'<animate attributeName="y" values="{base - a};{base - 12};{base - b};{base - a}" dur="{dur}" repeatCount="indefinite"/></rect>')
    inner = (panel(x, y, w, h, "#11131a", "rgba(255,255,255,0.10)", rx=14)
             + text(x + 18, y + 28, label.upper(), "m", 11, "#1DB954", 700, spacing=1.5)
             + bars
             + f'<rect x="{x + 18}" y="{y + 44}" width="44" height="44" rx="8" fill="#1DB954"/>'
             + f'<path d="M{x + 28} {y + 60}q12-4 24 2M{x + 29} {y + 67}q10-3 20 2M{x + 30} {y + 74}q8-2 16 1" '
               f'stroke="#0b0d12" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
             + text(x + 74, y + 62, (title or "")[:22], "b", 15, "#ffffff", 700)
             + text(x + 74, y + 82, (artist or "")[:30], "b", 12, "rgba(255,255,255,0.6)"))
    return tilt(x, y, w, h, -2.5, inner)


def postcard() -> str:
    x, y, w, h = 334, 296, 290, 198
    stripes = "".join(f'<rect x="{x + k * 12}" y="{y}" width="6" height="5" fill="{"#ef4444" if k % 2 == 0 else "#3b82f6"}"/>' for k in range(24))
    heights = [(22, "#c5cafc"), (34, "#9aa1f6"), (18, "#fbc7e6"), (44, "#6366f1"), (26, "#b9c6ff"), (16, "#fbc7e6"),
               (38, "#818cf8"), (24, "#c5cafc"), (30, "#9aa1f6"), (20, "#b9f4e6"), (28, "#c5cafc")]
    sky = "".join(f'<rect x="{x + 28 + k * 17}" y="{y + 100 - hh}" width="13" height="{hh}" fill="{c}"/>' for k, (hh, c) in enumerate(heights))
    inner = (panel(x, y, w, h, "#fbf6ea", rx=10) + stripes
             + f'<rect x="{x + 18}" y="{y + 22}" width="208" height="80" rx="6" fill="#f1eaff"/>' + sky
             + f'<rect x="{x + 234}" y="{y + 18}" width="40" height="52" rx="3" fill="#ffffff" stroke="#9aa0b5" stroke-dasharray="3 2"/>'
             + text(x + 254, y + 50, "BHX", "m", 12, INK, 700, anchor="middle")
             + text(x + 18, y + 128, "GREETINGS FROM", "m", 11, DIM, spacing=2)
             + text(x + 18, y + 154, "Birmingham, UK", "d", 22, INK, 700)
             + text(x + 18, y + 176, "52.48°N · open to remote & hybrid", "m", 12, MUTED))
    return tilt(x, y, w, h, -1.5, inner)


def stack() -> str:
    x, y, w, h = 664, 446, 506, 132
    rows = [("AI / ML", ["LLMs", "RAG", "PyTorch", "Vector search", "SHAP"]),
            ("LANGUAGES", ["Python", "C# / .NET", "TypeScript", "SQL"])]
    inner = panel(x, y, w, h, "#ffffff") + text(x + 20, y + 28, "STACK", "m", 12, DIM, 600, spacing=2)
    for r, (label, items) in enumerate(rows):
        yy = y + 44 + r * 42
        inner += text(x + 20, yy + 17, label, "m", 11, "#4f46e5", 600, spacing=1.5)
        cx = x + 118
        for item in items:
            cw = 18 + len(item) * 7.4
            inner += (f'<rect x="{cx:.0f}" y="{yy}" width="{cw:.0f}" height="26" rx="7" fill="#f6f6fc" stroke="{PAPER_LINE}"/>'
                      + text(round(cx + cw / 2), yy + 17, item, "m", 12, MUTED, anchor="middle"))
            cx += cw + 8
    return tilt(x, y, w, h, 1, inner)


def cards(t: dict, prs: list[dict], counts: dict, track: dict, photo: str) -> str:
    w, h = 1200, 610
    blobs = "".join(
        f'<radialGradient id="cg{i}"><stop offset="0" stop-color="{c}" stop-opacity="{t["mesh_opacity"]}"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>' for i, c in enumerate(t["mesh"]))
    shadow = "#1e1b4b" if t is THEMES["light"] else "#000000"
    body = (f'<defs>{clip(w, h)}{blobs}<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">'
            f'<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="{shadow}" flood-opacity="0.22"/></filter></defs>'
            f'<g clip-path="url(#clip)"><ellipse cx="200" cy="140" rx="360" ry="260" fill="url(#cg0)"/>'
            f'<ellipse cx="1050" cy="500" rx="380" ry="240" fill="url(#cg1)"/><ellipse cx="700" cy="80" rx="320" ry="200" fill="url(#cg2)"/>'
            f'<ellipse cx="450" cy="580" rx="360" ry="200" fill="url(#cg3)"/></g>{grid(w, h, t)}'
            f'<g clip-path="url(#clip)">{id_badge(photo)}{education()}{postcard()}{receipt(prs, counts)}{stack()}{terminal()}{music(track)}</g>')
    return svg(w, h, body, t, "Cards from usmanmateen.com: ID badge, education, a postcard from Birmingham, the open-source "
               "receipt, the stack, dissertation status and music.", ["Space Grotesk", "Inter", "JetBrains Mono", "Instrument Serif"])


def spotify() -> dict:
    """The site's own Spotify endpoint, as the Now Playing card on usmanmateen.com uses it."""
    try:
        with urllib.request.urlopen("https://usmanmateen.com/api/spotify", timeout=30) as resp:
            return json.load(resp)
    except Exception:
        return {}


# ── README tables ───────────────────────────────────────────────────────────

LABEL = {"merged": "Merged", "queued": "In merge queue", "approved": "Approved", "review": "In review", "superseded": "Superseded"}


def table(prs: list[dict]) -> str:
    rows = ["| Project | Pull request | Status |", "|---|---|---|"]
    for p in prs:
        repo = p["repository"]
        title = p["title"].replace("|", "\\|")
        status = LABEL[p["status"]]
        if p["status"] == "merged":
            status += f" {p['mergedAt'][:10]}"
        if p["key"] in NOTES:
            status += f" · {NOTES[p['key']]}"
        rows.append(f"| [{repo['nameWithOwner']}]({repo['url']}) | [{title}]({p['url']}) | {status} |")
    return "\n".join(rows)


def replace_block(text: str, name: str, body: str) -> str:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{body}\n{end}{tail}"


def main() -> None:
    prs = pull_requests()
    cal = calendar()
    # Organisation logos only: a person's avatar is their photo, so their repos get a lettered tile.
    owners = {p["repository"]["owner"]["login"]: p["repository"]["owner"]["avatarUrl"] for p in prs
              if p["repository"]["owner"]["__typename"] == "Organization"}
    avatars = {o: data_uri(url + ("&" if "?" in url else "?") + "s=192") for o, url in owners.items()}
    repos = {p["repository"]["nameWithOwner"]: p["repository"]["stargazerCount"] for p in prs}
    counts = {s: sum(p["status"] == s for p in prs) for s in LABEL}
    counts.update(projects=len(repos), stars=sum(repos.values()), date=dt.date.today().strftime("%d %b %Y"))

    track = spotify()
    photo = "data:image/jpeg;base64," + base64.b64encode((ASSETS / "me.jpg").read_bytes()).decode()
    for name, t in THEMES.items():
        (ASSETS / f"header-{name}.svg").write_text(header(t, counts), encoding="utf-8")
        (ASSETS / f"open-source-{name}.svg").write_text(open_source(t, prs, avatars, counts), encoding="utf-8")
        (ASSETS / f"activity-{name}.svg").write_text(activity(t, cal), encoding="utf-8")
        (ASSETS / f"cards-{name}.svg").write_text(cards(t, prs, counts, track, photo), encoding="utf-8")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    merged = [p for p in prs if p["status"] == "merged"]
    rest = [p for p in prs if p["status"] != "merged"]
    readme = replace_block(readme, "merged", table(merged))
    readme = replace_block(readme, "open", table(rest))
    readme = replace_block(readme, "counts",
                           f"**{counts['merged']} merged** · {counts['review'] + counts['approved'] + counts['queued']} open or in review, "
                           f"across {counts['projects']} projects with "
                           f"{counts['stars']:,} combined GitHub stars.")
    (ROOT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in counts.items()}, indent=1))


if __name__ == "__main__":
    main()

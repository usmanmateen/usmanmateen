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
        f'<text x="64" y="200" class="s" font-size="34" fill="{t["muted"]}">I build and ship production AI.</text>'
        f'<rect x="64" y="226" width="372" height="36" rx="18" fill="{t["surface"]}" stroke="{t["line"]}" stroke-width="2"/>'
        f'<circle cx="86" cy="244" r="6" fill="{t["sig"]}"/>'
        f'<text x="102" y="250" class="b" font-size="15" font-weight="600" fill="{t["sig_ink"]}">Open to mid-level AI / applied-AI roles</text>'
        + receipt
    )
    return svg(w, h, body, t, "Muhammad Usman Mateen, AI Engineer. I build and ship production AI.",
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

    for name, t in THEMES.items():
        (ASSETS / f"header-{name}.svg").write_text(header(t, counts), encoding="utf-8")
        (ASSETS / f"open-source-{name}.svg").write_text(open_source(t, prs, avatars, counts), encoding="utf-8")
        (ASSETS / f"activity-{name}.svg").write_text(activity(t, cal), encoding="utf-8")

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

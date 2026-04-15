import json
from collections import Counter
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from estimator import estimate_project, followup_estimate

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DEV_JSON = BASE_DIR / "examples" / "sample_output.json"
STATIC   = BASE_DIR / "static"

st.set_page_config(page_title="AI Project Estimator", page_icon="📋", layout="wide")

# ── Session state defaults ────────────────────────────────────────────────────
_DEFAULTS = {
    "dev_mode":    False,
    "brief_value": "",
    "brief_text":  "",
    "changes":     [],
    "reest_open":  False,
}
for _key, _val in _DEFAULTS.items():
    if _key not in st.session_state:
        st.session_state[_key] = _val

# ── Dev/Prod toggle ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Mode")
    toggled = st.toggle(
        "Dev mode",
        value=st.session_state.dev_mode,
        help="ON: load from saved JSON (no API calls)\nOFF: live API"
    )
    if toggled != st.session_state.dev_mode:
        st.session_state.dev_mode = toggled
        st.session_state.pop("estimate", None)
        st.session_state.changes = []
        st.rerun()
    st.caption("Dev - saved JSON" if st.session_state.dev_mode else "Live - API enabled")

DEV_MODE = st.session_state.dev_mode

# ── Load data ─────────────────────────────────────────────────────────────────
if DEV_MODE:
    with open(DEV_JSON) as f:
        data = json.load(f)
    est = data
    st.session_state.brief_text = data.get("_brief", "")
else:
    if "estimate" not in st.session_state:
        st.title("AI Project Estimator")
        st.markdown(
            "<p style='color:#777;font-size:14px;margin-bottom:1.2rem'>Paste a project brief - "
            "freeform is fine. Get a risk-aware, assumption-explicit estimate in seconds.</p>",
            unsafe_allow_html=True
        )
        example = (
            "Build a customer portal where enterprise clients can log in, view their invoices, "
            "download usage reports, and open support tickets. It needs to integrate with our "
            "existing Salesforce CRM and Stripe billing system. The team is 2 frontend engineers, "
            "1 backend engineer, and 1 designer. We would like to launch in Q2."
        )
        if st.button("Load example"):
            st.session_state.brief_value = example

        brief = st.text_area(
            "Project brief:",
            value=st.session_state.brief_value,
            height=180,
            placeholder="Describe your project - team, integrations, timeline, constraints..."
        )
        char_count = len(brief)
        if char_count > 3000:
            st.warning(
                f"Brief is {char_count:,} characters. For best results keep it under 3,000 - "
                "focus on team, integrations, timeline, and key constraints."
            )
        if st.button("Estimate", type="primary", disabled=not brief.strip()):
            with st.spinner("Analyzing scope, surfacing risks, building estimate..."):
                try:
                    result = estimate_project(brief)
                    st.session_state.estimate   = result
                    st.session_state.changes    = []
                    st.session_state.brief_text = brief
                    st.rerun()
                except Exception as e:
                    st.error(f"Estimation failed: {e}")
        st.stop()
    est = st.session_state.estimate


# ── RAID classifier ───────────────────────────────────────────────────────────
# ── RAID keyword fallback (used when model did not generate raid items) ──────
_RISK_KEYWORDS       = {"complex","unclear","undefined","custom","unknown","integration",
                         "sync","webhook","security","constrained","bottleneck","rework"}
_ASSUMPTION_KEYWORDS = {"existing","standard","no major","if not","assumes",
                         "already","configured","reusing"}
_DEPENDENCY_KEYWORDS = {"integration","salesforce","stripe","api","oauth",
                         "sandbox","third-party","external"}
_ISSUE_KEYWORDS      = {"not allocated","severely","bottleneck","who is","who owns"}
_HIGH_IMPACT_KEYS    = {"undefined","unclear","custom","security"}

# Map single-letter type codes to display labels
_RAID_LABELS = {"R": "Risk", "A": "Assumption", "I": "Issue", "D": "Dependency"}

def _keyword_classify(story: dict) -> list[dict]:
    """Keyword heuristic fallback — used when model-generated raid is absent."""
    text  = (story["title"] + " " + story.get("notes", "")).lower()
    size  = story.get("size", "M")
    items = []
    if any(k in text for k in _RISK_KEYWORDS) or size in ("L", "XL"):
        prob   = "H" if size == "XL" else ("M" if size == "L" else "L")
        impact = "H" if any(k in text for k in _HIGH_IMPACT_KEYS) else "M"
        items.append({"type":"R","label":"Risk","prob":prob,"impact":impact,
                      "description": story.get("notes") or f"Complexity risk in: {story['title']}"})
    if any(k in text for k in _ASSUMPTION_KEYWORDS):
        items.append({"type":"A","label":"Assumption","prob":"M","impact":"M",
                      "description": story.get("notes") or "Assumes standard conditions"})
    if any(k in text for k in _DEPENDENCY_KEYWORDS):
        items.append({"type":"D","label":"Dependency","prob":"M",
                      "impact":"H" if ("salesforce" in text or "stripe" in text) else "M",
                      "description": f"External dependency: {story['title']}"})
    if any(k in text for k in _ISSUE_KEYWORDS):
        items.append({"type":"I","label":"Issue","prob":"H","impact":"H",
                      "description": story.get("notes") or story["title"]})
    return items


def classify_raid(story: dict) -> list[dict]:
    """
    Hybrid RAID classifier.

    Primary:  use model-generated raid items when present (schema option 2).
              These are richer, context-aware, and apply PM expertise at generation time.
    Fallback: keyword heuristics when model did not produce raid items.
              Deterministic, always available, catches surface-level signals.

    All returned items are normalised to include a 'label' key for display.
    """
    model_raid = story.get("raid")

    if model_raid:
        # Normalise model items: add display label, ensure required keys present
        normalised = []
        for item in model_raid:
            t = item.get("type", "R")
            normalised.append({
                "type":        t,
                "label":       _RAID_LABELS.get(t, t),
                "prob":        item.get("prob",   "M"),
                "impact":      item.get("impact", "M"),
                "description": item.get("description", ""),
            })
        return normalised

    # Fallback: keyword heuristics
    return _keyword_classify(story)


# ── Markdown report ───────────────────────────────────────────────────────────
def build_markdown_report(est):
    lines = [f"# {est.get('project_title','')}\n", f"{est.get('summary','')}\n"]
    tl = est.get("timeline", {})
    lines += ["## Timeline",
              f"- Optimistic: {tl.get('optimistic_weeks')} weeks",
              f"- Realistic: {tl.get('realistic_weeks')} weeks",
              f"- Pessimistic: {tl.get('pessimistic_weeks')} weeks\n",
              "### Assumptions"]
    lines += [f"- {a}" for a in tl.get("assumptions", [])]
    lines.append("\n## Scope Breakdown")
    for epic in est.get("scope_breakdown", []):
        lines.append(f"\n### {epic['epic']}")
        for s in epic.get("stories", []):
            suffix = f" - {s['notes']}" if s.get("notes") else ""
            lines.append(f"- [{s.get('size','M')}] {s['title']}{suffix}")
    lines.append("\n## Risks")
    for r in est.get("risks", []):
        lines.append(f"\n**{r['risk']}**  \nLikelihood: {r.get('likelihood')} | Impact: {r.get('impact')}  \nMitigation: {r.get('mitigation')}")
    lines.append("\n## Open Questions")
    lines += [f"- {q}" for q in est.get("open_questions", []) if q.strip() != "?"]
    return "\n".join(lines)


# ── HTML sub-builders ─────────────────────────────────────────────────────────
_SIZE_CSS    = {"S":"pill-S","M":"pill-M","L":"pill-L","XL":"pill-XL"}
_CONF_COLORS = {"Low":"#ef4444","Medium":"#f59e0b","High":"#22c55e"}
_WARN_KEYS   = {"NOT ALLOCATED","SEVERELY","BOTTLENECK","SPOF","MISSING"}

def _pct_color(pct):
    return "#ef4444" if pct < 45 else ("#f59e0b" if pct < 70 else "#22c55e")

def _build_brief_panel(brief_text):
    if not brief_text.strip():
        return ""
    preview = brief_text[:500]
    escaped = preview.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    if len(brief_text) > 500:
        escaped += " ..."
    return (
        '<div class="res-toggle" onclick="togglePanel(\'brief-panel\',\'brief-arrow\')">'
        '<span class="conf-label">Project brief</span>'
        '<span class="conf-arrow" id="brief-arrow">&#9658;</span>'
        '</div>'
        '<div class="res-panel" id="brief-panel">'
        '<p style="font-size:13px;color:#666;line-height:1.6;white-space:pre-wrap;margin:6px 0 4px">'
        + escaped + '</p></div>'
    )

def _build_resourcing_html(res):
    role_rows = ""
    for role in res.get("roles", []):
        fte   = role.get("fte", 0)
        notes = role.get("notes", "")
        warn  = fte == 0 or any(k in notes.upper() for k in _WARN_KEYS)
        nc    = "#f87171" if warn else "#bbb"
        fc    = "#555"    if fte == 0 else "#e8e8e8"
        noc   = "#f87171" if warn else "#666"
        role_rows += (
            '<div class="res-row">'
            '<span class="res-role" style="color:' + nc + '">' + role.get("role","") + '</span>'
            '<span class="res-fte" style="color:' + fc + '">' + str(fte) + ' FTE</span>'
            '<span class="res-note" style="color:' + noc + '">' + notes + '</span>'
            '</div>'
        )
    flag_rows = "".join('<div class="res-flag">! ' + f + '</div>' for f in res.get("red_flags", []))
    flags_section = ('<div class="section-hdr" style="margin-top:10px">Red flags</div>' + flag_rows) if flag_rows else ""
    return (
        '<div class="res-toggle" onclick="togglePanel(\'res-panel\',\'res-arrow\')">'
        '<span class="conf-label">Resourcing detail</span>'
        '<span class="conf-arrow" id="res-arrow">&#9658;</span>'
        '</div>'
        '<div class="res-panel" id="res-panel">' + role_rows + flags_section + '</div>'
    )

import math as _math

def _gauge_path(cx, cy, r, start_deg, end_deg):
    s  = _math.radians(start_deg)
    e  = _math.radians(end_deg)
    ir = r - 38
    ox1 = cx + r  * _math.cos(s);  oy1 = cy - r  * _math.sin(s)
    ox2 = cx + r  * _math.cos(e);  oy2 = cy - r  * _math.sin(e)
    ix1 = cx + ir * _math.cos(s);  iy1 = cy - ir * _math.sin(s)
    ix2 = cx + ir * _math.cos(e);  iy2 = cy - ir * _math.sin(e)
    lg  = 1 if abs(end_deg - start_deg) > 180 else 0
    return (f"M {ox1:.1f} {oy1:.1f} A {r} {r} 0 {lg} 0 {ox2:.1f} {oy2:.1f} "
            f"L {ix2:.1f} {iy2:.1f} A {ir} {ir} 0 {lg} 1 {ix1:.1f} {iy1:.1f} Z")

def _build_gauge_svg(sc_pct, dimensions):
    """SVG semicircle gauge. 5 neutral segments, needle at overall_pct."""
    cx, cy, r = 130, 158, 108
    gap    = 3
    n      = 5
    seg    = (180 - gap * (n - 1)) / n
    colors = ["#3d3d52","#4e4e68","#5f5f7e","#707094","#8181aa"]
    needle_rad = _math.radians(180 - (sc_pct / 100) * 180)
    nl   = 80
    nx   = cx + nl * _math.cos(needle_rad)
    ny   = cy - nl * _math.sin(needle_rad)
    paths = ""
    for i in range(n):
        start   = 180 - i * (seg + gap)
        end     = start - seg
        score   = dimensions[i].get("score", 0) if i < len(dimensions) else 0
        opacity = round(0.40 + (score / 10) * 0.60, 2)
        paths  += ('<path d="' + _gauge_path(cx, cy, r, end, start) + '" '
                   'fill="' + colors[i] + '" fill-opacity="' + str(opacity) + '" '
                   'stroke="#1a1a2a" stroke-width="1.5"/>')
    ticks = ""
    for t in range(0, 101, 10):
        a  = _math.radians(180 - t * 1.8)
        r1 = r - 6
        r2 = r - 14 if t % 50 == 0 else r - 10
        ticks += ('<line x1="' + f"{cx+r1*_math.cos(a):.1f}" + '" y1="' + f"{cy-r1*_math.sin(a):.1f}" + '" '
                  'x2="' + f"{cx+r2*_math.cos(a):.1f}" + '" y2="' + f"{cy-r2*_math.sin(a):.1f}" + '" '
                  'stroke="#444" stroke-width="1"/>')
    pct_color = "#ef4444" if sc_pct < 45 else ("#f59e0b" if sc_pct < 70 else "#22c55e")
    return (
        '<svg viewBox="0 0 260 200" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:260px;height:auto;display:block">'
        + paths + ticks
        + '<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="72" fill="#0d0d14" stroke="#222" stroke-width="1"/>'
        + '<line x1="' + str(cx) + '" y1="' + str(cy) + '" x2="' + f"{nx:.1f}" + '" y2="' + f"{ny:.1f}" + '" stroke="#ddd" stroke-width="2.5" stroke-linecap="round"/>'
        + '<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="7" fill="#ccc" stroke="#111" stroke-width="1.5"/>'
        + '<text x="' + str(cx) + '" y="' + str(cy+26) + '" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="22" font-weight="700" fill="' + pct_color + '">' + str(sc_pct) + '%</text>'
        + '<text x="' + str(cx) + '" y="' + str(cy+42) + '" text-anchor="middle" font-family="IBM Plex Sans,sans-serif" font-size="9" fill="#555">CONFIDENCE</text>'
        + '<text x="44.8" y="135.3" font-family="IBM Plex Sans,sans-serif" font-size="9" font-weight="700" fill="#ccc" text-anchor="middle">Scope</text>'
        + '<text x="76.9" y="89.5"  font-family="IBM Plex Sans,sans-serif" font-size="9" font-weight="700" fill="#ccc" text-anchor="middle">Team</text>'
        + '<text x="130"  y="72.0"  font-family="IBM Plex Sans,sans-serif" font-size="9" font-weight="700" fill="#ccc" text-anchor="middle">Integ.</text>'
        + '<text x="183.1" y="89.5" font-family="IBM Plex Sans,sans-serif" font-size="9" font-weight="700" fill="#ccc" text-anchor="middle">Timeline</text>'
        + '<text x="215.2" y="135.3" font-family="IBM Plex Sans,sans-serif" font-size="9" font-weight="700" fill="#ccc" text-anchor="middle">Assumpt.</text>'
        + '</svg>'
    )

def _build_scorecard_html(sc):
    if not sc.get("dimensions"):
        return ""
    sc_pct     = sc.get("overall_pct", 0)
    dimensions = sc["dimensions"]
    gauge_svg  = _build_gauge_svg(sc_pct, dimensions)

    # Right panel: dimension rows — name, score badge, bar, rationale, action
    dim_rows = ""
    for dim in dimensions:
        score   = dim.get("score", 0)
        d_color = "#ef4444" if score <= 3 else ("#f59e0b" if score <= 6 else "#22c55e")
        bar_pct = score * 10
        dim_rows += (
            '<div class="sc2-row">'
            '<div class="sc2-header">'
            '<span class="sc2-name">' + dim.get("dimension","") + '</span>'
            '<span class="sc2-score" style="color:' + d_color + '">' + str(score) + '/10</span>'
            '</div>'
            '<div class="sc2-bar-wrap"><div class="sc2-bar" style="width:' + str(bar_pct) + '%;background:' + d_color + '"></div></div>'
            '<div class="sc2-rationale">' + dim.get("rationale","") + '</div>'
            '<div class="sc2-action">&#8594; ' + dim.get("action","") + '</div>'
            '</div>'
        )

    return (
        '<div class="sc2-wrap">'
        '<div class="sc2-left">' + gauge_svg + '</div>'
        '<div class="sc2-right">' + dim_rows + '</div>'
        '</div>'
    )

def _build_metrics_html(est, brief_panel, resourcing_html):
    tl   = est["timeline"]
    res  = est["resourcing"]
    conf = est["confidence"]
    sc   = est.get("confidence_scorecard", {})
    clvl = conf["level"]
    conf_color = _CONF_COLORS.get(clvl, "#aaa")
    sc_pct     = sc.get("overall_pct", 0)
    pct_badge  = (' <span style="color:' + _pct_color(sc_pct) + ';font-family:IBM Plex Mono,monospace;font-size:13px">(' + str(sc_pct) + '%)</span>') if sc_pct else ""
    ci_items   = "".join('<div class="conf-item">-&gt; ' + f + '</div>' for f in conf.get("what_would_increase_confidence", []))
    return (
        '<div class="summary-bar">'
        '<div class="summary-cell"><div class="lbl" style="color:#60a5fa">Optimistic</div><div class="val">' + str(tl["optimistic_weeks"]) + 'w</div></div>'
        '<div class="summary-cell"><div class="lbl" style="color:#4ade80">Realistic</div><div class="val">' + str(tl["realistic_weeks"]) + 'w</div></div>'
        '<div class="summary-cell"><div class="lbl" style="color:#f87171">Pessimistic</div><div class="val">' + str(tl["pessimistic_weeks"]) + 'w</div></div>'
        '<div class="summary-cell"><div class="lbl" style="color:#d4b44a">Team size</div><div class="val">' + str(res["total_fte"]) + ' FTE</div></div>'
        '</div>'
        + brief_panel
        + resourcing_html
        + '<div class="conf-row" onclick="toggleConf()">'
        + '<span class="conf-label">Confidence: <span style="color:' + conf_color + '">' + clvl + '</span>' + pct_badge + '</span>'
        + '<span class="conf-arrow" id="conf-arrow">&#9658;</span>'
        + '</div>'
        + '<div class="conf-panel" id="conf-panel">'
        + '<p class="conf-rationale">' + conf.get("rationale","") + '</p>'
        + _build_scorecard_html(sc)
        + '<div class="section-hdr" style="margin-top:14px">To increase confidence</div>'
        + ci_items
        + '</div>'
        + '<hr class="divider">'
    )

def _build_story_html(story, ei, si, open_questions):
    size  = story.get("size","M")
    raid  = classify_raid(story)
    desc  = story.get("notes") or "Standard implementation - no specific complexity flagged."
    sid   = "s" + str(ei) + "_" + str(si)
    raid_badges = "".join('<span class="raid-tag tag-' + r["type"] + '">' + r["type"] + '</span>' for r in raid)
    badges_html = '<span class="pill ' + _SIZE_CSS.get(size,"pill-M") + '">' + size + '</span>' + raid_badges
    raid_rows   = "".join(
        '<div class="detail-row">'
        '<span class="raid-tag tag-' + r["type"] + '">' + r["label"] + '</span>'
        '<span class="impact impact-' + r["prob"] + '">P:' + r["prob"] + '</span>'
        '<span class="impact impact-' + r["impact"] + '">I:' + r["impact"] + '</span>'
        '<span class="detail-text">' + r["description"] + '</span>'
        '</div>'
        for r in raid
    )
    raid_section = ('<div class="section-hdr">RAID</div>' + raid_rows) if raid_rows else ""
    story_text   = (story["title"] + " " + story.get("notes","")).lower()
    matched_qs   = [q for q in open_questions if any(w in q.lower() for w in story_text.split() if len(w) > 4)][:3]
    qs_rows      = "".join('<div class="detail-row"><span class="detail-text">' + q + '</span></div>' for q in matched_qs)
    qs_section   = ('<div class="section-hdr">Open Questions</div>' + qs_rows) if qs_rows else ""
    return (
        '<div class="story-row" onclick="toggleStory(\'' + sid + '\')">'
        '<span class="chev">&#9658;</span>'
        '<span class="badges">' + badges_html + '</span>'
        '<span class="story-title">' + story["title"] + '</span>'
        '</div>'
        '<div class="story-detail" id="' + sid + '">'
        '<p class="desc-text">' + desc + '</p>'
        + raid_section + qs_section +
        '</div>'
    )

def _build_epics_html(est):
    RAID_TYPES     = ["R","A","I","D"]
    open_questions = est.get("open_questions", [])
    html           = ""
    for ei, epic in enumerate(est["scope_breakdown"]):
        stories         = epic.get("stories", [])
        size_counts     = Counter(s.get("size","M") for s in stories)
        epic_raid_types = {r["type"] for story in stories for r in classify_raid(story)}
        size_pills = "".join(
            '<span class="pill ' + _SIZE_CSS[sz] + '" style="position:relative;margin-right:14px">'
            + sz + '<span class="pill-count">' + str(size_counts[sz]) + '</span></span>'
            for sz in ["XL","L","M","S"] if size_counts[sz]
        )
        raid_ind = "".join(
            '<span class="raid-tag tag-' + t + '">' + t + '</span>' if t in epic_raid_types
            else '<span class="raid-absent">-</span>'
            for t in RAID_TYPES
        )
        stories_html = "".join(_build_story_html(s, ei, si, open_questions) for si, s in enumerate(stories))
        eid  = "e" + str(ei)
        html += (
            '<div class="epic-row" onclick="toggleEpic(\'' + eid + '\')">'
            '<span class="chev">&#9658;</span>'
            '<span class="epic-badges">' + size_pills + '</span>'
            '<span class="epic-title">' + epic["epic"] + '</span>'
            '<span class="epic-raid">' + raid_ind + '</span>'
            '</div>'
            '<div class="epic-body" id="' + eid + '">' + stories_html + '</div>'
        )
    return html

def _build_reestimate_html():
    return (
        '<hr style="border:none;border-top:1px solid #4a9eff;margin:16px 0 6px;opacity:0.3">'
        '<div class="epic-row" onclick="toggleReest()">'
        '<span class="chev" id="reest-chev">&#9658;</span>'
        '<span class="epic-badges"></span>'
        '<span class="epic-title" style="color:#666">Re-estimate under different constraints</span>'
        '</div>'
        '<div id="reest-panel" style="display:none;padding:14px 0 10px 94px">'
        '<textarea id="reest-input" placeholder="e.g. What if we drop usage reports from v1?" '
        'style="width:100%;height:90px;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:4px;'
        'color:#ccc;font-family:IBM Plex Sans,sans-serif;font-size:14px;padding:10px;resize:vertical"></textarea>'
        '<div style="margin-top:8px;font-size:12px;color:#444">Use the Dev mode toggle in the sidebar to enable live re-estimation.</div>'
        '</div>'
    )


def build_html(est, brief_text=""):
    """
    Orchestrates all sub-builders into a single self-contained HTML document.
    CSS loaded from static/styles.css, JS from static/scripts.js.
    """
    css = (STATIC / "styles.css").read_text()
    js  = (STATIC / "scripts.js").read_text()

    brief_panel     = _build_brief_panel(brief_text)
    resourcing_html = _build_resourcing_html(est["resourcing"])
    metrics_html    = _build_metrics_html(est, brief_panel, resourcing_html)
    epics_html      = _build_epics_html(est)
    reestimate_html = _build_reestimate_html()

    # Calculate height from content rather than hardcoding
    n_epics   = len(est.get("scope_breakdown", []))
    n_stories = sum(len(e.get("stories", [])) for e in est.get("scope_breakdown", []))
    height    = 300 + (n_epics * 46) + (n_stories * 40)

    doc = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>' + css + '</style>'
        '</head><body>'
        + metrics_html + epics_html + reestimate_html
        + '<script>' + js + '</script>'
        '</body></html>'
    )
    return doc, height


# ── Render ────────────────────────────────────────────────────────────────────
st.markdown(f"## {est['project_title']}")
st.markdown(
    f"<p style='color:#777;font-size:14px;margin-bottom:1rem;line-height:1.6'>{est['summary']}</p>",
    unsafe_allow_html=True
)

if st.session_state.changes:
    for c in st.session_state.changes:
        st.markdown(
            f"<div style='background:#1a1200;border-left:3px solid #f59e0b;"
            f"padding:6px 12px;margin:4px 0;font-size:13px;color:#d4b44a'>change: {c}</div>",
            unsafe_allow_html=True
        )

html_content, iframe_height = build_html(est, st.session_state.brief_text)
components.html(html_content, height=iframe_height, scrolling=False)

# ── Downloads ─────────────────────────────────────────────────────────────────
st.markdown("---")
col_a, col_b = st.columns(2)
with col_a:
    st.download_button("Download JSON", data=json.dumps(est, indent=2),
                       file_name="estimate.json", mime="application/json")
with col_b:
    st.download_button("Download Markdown", data=build_markdown_report(est),
                       file_name="estimate.md", mime="text/markdown")

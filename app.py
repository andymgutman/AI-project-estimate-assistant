import streamlit as st
import streamlit.components.v1 as components
import json
from pathlib import Path

DEV_JSON = Path(__file__).parent / "examples" / "sample_output.json"

st.set_page_config(page_title="AI Project Estimator", page_icon="📋", layout="wide")

# ── Dev/Prod toggle ───────────────────────────────────────────────────────────
if "dev_mode" not in st.session_state:
    st.session_state.dev_mode = False

with st.sidebar:
    st.markdown("### ⚙️ Mode")
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
    if st.session_state.dev_mode:
        st.caption("🛠 Dev — saved JSON, no API calls")
    else:
        st.caption("🟢 Live — API enabled")

DEV_MODE = st.session_state.dev_mode

# ── Load data ─────────────────────────────────────────────────────────────────
if DEV_MODE:
    with open(DEV_JSON) as f:
        est = json.load(f)
else:
    if "estimate" not in st.session_state:
        st.title("📋 AI Project Estimator")
        st.markdown(
            "<p style='color:#777;font-size:14px;margin-bottom:1.2rem'>Paste a project brief — "
            "freeform is fine. Get a risk-aware, assumption-explicit estimate in seconds.</p>",
            unsafe_allow_html=True
        )
        if "brief_value" not in st.session_state:
            st.session_state.brief_value = ""

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
            placeholder="Describe your project — team, integrations, timeline, constraints..."
        )
        if st.button("Estimate →", type="primary", disabled=not brief.strip()):
            from estimator import estimate_project
            with st.spinner("Analyzing scope, surfacing risks, building estimate..."):
                try:
                    result = estimate_project(brief)
                    st.session_state.estimate = result
                    st.session_state.changes  = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Estimation failed: {e}")
        st.stop()
    est = st.session_state.estimate

# ── Session state ─────────────────────────────────────────────────────────────
if "changes"    not in st.session_state: st.session_state.changes    = []
if "reest_open" not in st.session_state: st.session_state.reest_open = False

# ── RAID classifier ───────────────────────────────────────────────────────────
def classify_raid(story):
    title = story["title"].lower()
    notes = story.get("notes", "").lower()
    text  = title + " " + notes
    items = []
    if any(k in text for k in ["complex","unclear","undefined","custom","unknown","integration",
           "sync","webhook","security","constrained","bottleneck","rework"]) or story.get("size") in ("L","XL"):
        prob   = "H" if story.get("size") == "XL" else ("M" if story.get("size") == "L" else "L")
        impact = "H" if any(k in text for k in ["undefined","unclear","custom","security"]) else "M"
        items.append({"type":"R","label":"Risk","prob":prob,"impact":impact,
                      "description": story.get("notes") or f"Complexity risk in: {story['title']}"})
    if any(k in text for k in ["existing","standard","no major","if not","assumes","already","configured","reusing"]):
        items.append({"type":"A","label":"Assumption","prob":"M","impact":"M",
                      "description": story.get("notes") or f"Assumes standard conditions"})
    if any(k in text for k in ["integration","salesforce","stripe","api","oauth","sandbox","third-party","external"]):
        items.append({"type":"D","label":"Dependency","prob":"M",
                      "impact":"H" if "salesforce" in text or "stripe" in text else "M",
                      "description": f"External dependency: {story['title']}"})
    if any(k in text for k in ["not allocated","severely","bottleneck","who is","who owns"]):
        items.append({"type":"I","label":"Issue","prob":"H","impact":"H",
                      "description": story.get("notes") or story["title"]})
    return items

# ── Build the full HTML tree ───────────────────────────────────────────────────
def size_css(s):
    return {"S":"pill-S","M":"pill-M","L":"pill-L","XL":"pill-XL"}.get(s,"pill-M")

def build_html(est):
    from collections import Counter

    tl   = est["timeline"]
    res  = est["resourcing"]
    conf = est["confidence"]
    clvl = conf["level"]
    conf_color = {"Low":"#ef4444","Medium":"#f59e0b","High":"#22c55e"}.get(clvl,"#aaa")

    ci_items = "".join(
        "<div class='conf-item'>→ " + f + "</div>"
        for f in conf["what_would_increase_confidence"]
    )
    metrics_html = (
        '<div class="summary-bar">'
        '<div class="summary-cell"><div class="lbl" style="color:#60a5fa">Optimistic</div><div class="val">' + str(tl["optimistic_weeks"]) + 'w</div></div>'
        '<div class="summary-cell"><div class="lbl" style="color:#4ade80">Realistic</div><div class="val">' + str(tl["realistic_weeks"]) + 'w</div></div>'
        '<div class="summary-cell"><div class="lbl" style="color:#f87171">Pessimistic</div><div class="val">' + str(tl["pessimistic_weeks"]) + 'w</div></div>'
        '<div class="summary-cell"><div class="lbl" style="color:#d4b44a">Team size</div><div class="val">' + str(res["total_fte"]) + ' FTE</div></div>'
        '</div>'
        '<div class="conf-row" onclick="toggleConf()">'
        '<span class="conf-label">Confidence: <span style="color:' + conf_color + '">' + clvl + '</span></span>'
        '<span class="conf-arrow" id="conf-arrow">▶</span>'
        '</div>'
        '<div class="conf-panel" id="conf-panel">'
        '<p class="conf-rationale">' + conf["rationale"] + '</p>'
        '<div class="section-hdr">To increase confidence</div>'
        + ci_items +
        '</div>'
        '<hr class="divider">'
    )

    RAID_TYPES = ["R", "A", "I", "D"]

    epics_html = ""
    for ei, epic in enumerate(est["scope_breakdown"]):

        size_counts  = Counter(s.get("size", "M") for s in epic.get("stories", []))
        epic_raid_types = set()
        for story in epic.get("stories", []):
            for r in classify_raid(story):
                epic_raid_types.add(r["type"])

        # Size pills with circled count superscript — only present sizes
        size_pills = ""
        for sz in ["XL", "L", "M", "S"]:
            if size_counts[sz]:
                size_pills += (
                    '<span class="pill pill-' + sz + '" style="position:relative;margin-right:14px">'
                    + sz +
                    '<span class="pill-count">' + str(size_counts[sz]) + '</span>'
                    '</span>'
                )

        # RAID indicators — lit if present, dash if absent
        raid_ind = ""
        for t in RAID_TYPES:
            if t in epic_raid_types:
                raid_ind += '<span class="raid-tag tag-' + t + '">' + t + '</span>'
            else:
                raid_ind += '<span class="raid-absent">–</span>'

        stories_html = ""
        for si, story in enumerate(epic.get("stories", [])):
            size = story.get("size", "M")
            raid = classify_raid(story)
            desc = story.get("notes") or "Standard implementation — no specific complexity flagged."

            # RAID detail rows
            raid_rows = ""
            for r in raid:
                raid_rows += (
                    '<div class="detail-row">'
                    '<span class="raid-tag tag-' + r["type"] + '">' + r["label"] + '</span>'
                    '<span class="impact impact-' + r["prob"] + '">P:' + r["prob"] + '</span>'
                    '<span class="impact impact-' + r["impact"] + '">I:' + r["impact"] + '</span>'
                    '<span class="detail-text">' + r["description"] + '</span>'
                    '</div>'
                )
            raid_html = ('<div class="section-hdr">RAID</div>' + raid_rows) if raid_rows else ""

            # Open questions matched to this story
            story_text = (story["title"] + " " + story.get("notes", "")).lower()
            story_qs = [q for q in est.get("open_questions", [])
                        if any(w in q.lower() for w in story_text.split() if len(w) > 4)][:3]
            qs_rows = "".join(
                '<div class="detail-row"><span class="detail-text">' + q + '</span></div>'
                for q in story_qs
            )
            qs_html = ('<div class="section-hdr">Open Questions</div>' + qs_rows) if qs_rows else ""

            # Story badges LEFT of title: size pill + RAID tags
            story_raid = "".join(
                '<span class="raid-tag tag-' + r["type"] + '">' + r["type"] + '</span>'
                for r in raid
            )
            story_badges = '<span class="pill pill-' + size + '">' + size + '</span>' + story_raid

            sid = "s" + str(ei) + "_" + str(si)
            stories_html += (
                '<div class="story-row" onclick="toggleStory(\'' + sid + '\')">'
                '<span class="chev">▶</span>'
                '<span class="badges">' + story_badges + '</span>'
                '<span class="story-title">' + story["title"] + '</span>'
                '</div>'
                '<div class="story-detail" id="' + sid + '">'
                '<p class="desc-text">' + desc + '</p>'
                + raid_html + qs_html +
                '</div>'
            )

        eid = "e" + str(ei)
        epics_html += (
            '<div class="epic-row" onclick="toggleEpic(\'' + eid + '\')">'
            '<span class="chev">▶</span>'
            '<span class="epic-badges">' + size_pills + '</span>'
            '<span class="epic-title">' + epic["epic"] + '</span>'
            '<span class="epic-raid">' + raid_ind + '</span>'
            '</div>'
            '<div class="epic-body" id="' + eid + '">' + stories_html + '</div>'
        )

    css = (
        "* { box-sizing: border-box; margin: 0; padding: 0; }"
        'body { font-family: "IBM Plex Sans", sans-serif; background: transparent; color: #ccc; padding: 4px 0; }'
        ".summary-bar { display:flex; gap:36px; margin-bottom:1.2rem; }"
        ".lbl { font-size:11px; font-weight:600; letter-spacing:.09em; text-transform:uppercase; color:#555; margin-bottom:4px; }"
        '.val { font-family:"IBM Plex Mono",monospace; font-size:26px; font-weight:600; color:#e8e8e8; }'
        ".conf-row { display:flex; align-items:center; gap:10px; cursor:pointer; padding:8px 0; user-select:none; }"
        ".conf-row:hover .conf-label { color:#fff; }"
        ".conf-label { font-size:14px; color:#888; }"
        ".conf-arrow { font-size:11px; color:#555; transition:transform .2s; }"
        ".conf-panel { display:none; padding:10px 0 14px 0; }"
        ".conf-rationale { font-size:14px; color:#888; line-height:1.6; margin-bottom:10px; }"
        ".conf-item { font-size:13px; color:#777; padding:4px 0; border-bottom:1px solid #1a1a1a; }"
        ".conf-item:last-child { border-bottom:none; }"
        ".divider { border:none; border-top:1px solid #1e1e1e; margin:10px 0 6px; }"
        ".epic-row { display:grid; grid-template-columns:14px 160px 1fr auto; align-items:center; gap:10px; padding:12px 0; border-bottom:1px solid #222; cursor:pointer; user-select:none; }"
        ".epic-row:hover { background:#0d0d0d; }"
        ".epic-badges { display:flex; gap:16px; align-items:center; }"
        ".epic-title { font-size:15px; font-weight:600; color:#ddd; }"
        ".epic-raid { display:flex; gap:5px; align-items:center; flex-shrink:0; }"
        ".epic-body { display:none; }"
        ".story-row { display:grid; grid-template-columns:14px 100px 1fr; align-items:center; gap:10px; padding:9px 0 9px 60px; border-bottom:1px solid #1a1a1a; cursor:pointer; user-select:none; }"
        ".story-row:hover { background:#0a0a0a; }"
        ".story-title { font-size:14px; color:#bbb; }"
        ".badges { display:flex; gap:5px; align-items:center; }"
        ".story-detail { display:none; padding:10px 0 14px 194px; border-bottom:1px solid #1a1a1a; }"
        ".chev { color:#555; font-size:11px; width:14px; flex-shrink:0; transition:transform .15s; display:inline-block; }"
        ".chev.open { transform:rotate(90deg); color:#888; }"
        '.pill { font-family:"IBM Plex Mono",monospace; font-size:13px; font-weight:700; padding:3px 10px; border-radius:4px; position:relative; display:inline-block; }'
        ".pill-S  { background:#0d2137; color:#60a5fa; min-width:32px; text-align:center; }"
        ".pill-M  { background:#1a1a0d; color:#d4b44a; min-width:32px; text-align:center; }"
        ".pill-L  { background:#1a0d1a; color:#c084fc; min-width:32px; text-align:center; }"
        ".pill-XL { background:#1a0d0d; color:#f87171; min-width:38px; text-align:center; }"
        ".pill-count { position:absolute; top:-8px; right:-11px; background:#2a2a2a; color:#ddd; font-size:10px; font-weight:700; width:17px; height:17px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-family:\"IBM Plex Mono\",monospace; border:1px solid #555; }"
        '.raid-tag { font-size:12px; font-weight:700; padding:3px 9px; border-radius:4px; font-family:"IBM Plex Mono",monospace; }'
        ".tag-R { background:#2a0d0d; color:#f87171; }"
        ".tag-A { background:#1a1400; color:#fbbf24; }"
        ".tag-I { background:#001a2a; color:#60a5fa; }"
        ".tag-D { background:#0d1a0d; color:#4ade80; }"
        ".raid-absent { font-size:14px; color:#2a2a2a; font-weight:700; padding:0 3px; }"
        '.impact { font-size:12px; padding:3px 9px; border-radius:4px; font-family:"IBM Plex Mono",monospace; font-weight:600; }'
        ".impact-H { background:#2a0d0d; color:#f87171; }"
        ".impact-M { background:#1a1200; color:#fbbf24; }"
        ".impact-L { background:#0d1a0d; color:#4ade80; }"
        ".section-hdr { font-size:12px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:#c8c8c8; margin:12px 0 7px; border-left:3px solid #444; padding-left:8px; }"
        ".detail-row { display:flex; align-items:flex-start; gap:8px; padding:6px 0; border-bottom:1px solid #141414; }"
        ".detail-row:last-child { border-bottom:none; }"
        ".detail-text { font-size:14px; color:#999; line-height:1.5; }"
        ".desc-text { font-size:15px; color:#888; line-height:1.6; margin-bottom:2px; }"
    )

    js = (
        "function toggleConf(){"
        "var p=document.getElementById('conf-panel');"
        "var a=document.getElementById('conf-arrow');"
        "var o=p.style.display==='block';"
        "p.style.display=o?'none':'block';"
        "a.style.transform=o?'':'rotate(90deg)';}"
        "function toggleEpic(id){"
        "var b=document.getElementById(id);"
        "var r=b.previousElementSibling;"
        "var c=r.querySelector('.chev');"
        "var o=b.style.display==='block';"
        "b.style.display=o?'none':'block';"
        "if(c)c.classList.toggle('open',!o);}"
        "function toggleStory(id){"
        "var d=document.getElementById(id);"
        "var r=d.previousElementSibling;"
        "var c=r.querySelector('.chev');"
        "var o=d.style.display==='block';"
        "d.style.display=o?'none':'block';"
        "if(c)c.classList.toggle('open',!o);}"
    )

    reestimate_html = (
        '<hr style="border:none;border-top:1px solid #4a9eff;margin:16px 0 6px;opacity:0.3">'
        '<div class="epic-row" onclick="toggleReest()" style="color:#777">'
        '<span class="chev" id="reest-chev">▶</span>'
        '<span style="font-size:14px;color:#666;padding-left:4px">Re-estimate under different constraints</span>'
        '</div>'
        '<div id="reest-panel" style="display:none;padding:14px 0 10px 28px">'
        '<textarea id="reest-input" placeholder="e.g. What if we drop usage reports from v1?&#10;What if we add a second backend engineer?" '
        'style="width:100%;height:90px;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:4px;'
        'color:#ccc;font-family:IBM Plex Sans,sans-serif;font-size:14px;padding:10px;resize:vertical"></textarea>'
        '<div style="margin-top:8px;font-size:12px;color:#444">'
        'Use the Dev mode toggle in the sidebar to enable live re-estimation.'
        '</div></div>'
    )

    reest_js = (
        'function toggleReest(){'
        'var p=document.getElementById("reest-panel");'
        'var c=document.getElementById("reest-chev");'
        'var o=p.style.display==="block";'
        'p.style.display=o?"none":"block";'
        'if(c)c.classList.toggle("open",!o);}'
    )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">'
        '<style>' + css + '</style></head>'
        '<body>' + metrics_html + epics_html + reestimate_html
        + '<script>' + js + reest_js + '</script>'
        '</body></html>'
    )

html_content = build_html(est)

# ── Render title + summary outside component ──────────────────────────────────
st.markdown(f"## {est['project_title']}")
st.markdown(f"<p style='color:#777;font-size:14px;margin-bottom:1rem;line-height:1.6'>{est['summary']}</p>",
            unsafe_allow_html=True)

if st.session_state.changes:
    for c in st.session_state.changes:
        st.markdown(f"<div style='background:#1a1200;border-left:3px solid #f59e0b;padding:6px 12px;margin:4px 0;font-size:13px;color:#d4b44a'>↻ {c}</div>",
                    unsafe_allow_html=True)

# Render the self-contained HTML tree
components.html(html_content, height=2278, scrolling=False)

# Re-estimate is now inside the HTML component


# ── Downloads ─────────────────────────────────────────────────────────────────
st.markdown("---")

def build_markdown_report(est):
    lines = [f"# {est.get('project_title','')}\n", f"{est.get('summary','')}\n"]
    tl = est.get("timeline", {})
    lines += ["## Timeline",
              f"- Optimistic: {tl.get('optimistic_weeks')} weeks",
              f"- Realistic: {tl.get('realistic_weeks')} weeks",
              f"- Pessimistic: {tl.get('pessimistic_weeks')} weeks\n","### Assumptions"]
    lines += [f"- {a}" for a in tl.get("assumptions", [])]
    lines.append("\n## Scope Breakdown")
    for epic in est.get("scope_breakdown", []):
        lines.append(f"\n### {epic['epic']}")
        for s in epic.get("stories", []):
            lines.append(f"- [{s.get('size','M')}] {s['title']}" + (f" — {s['notes']}" if s.get("notes") else ""))
    lines.append("\n## Risks")
    for r in est.get("risks", []):
        lines.append(f"\n**{r['risk']}**  \nLikelihood: {r.get('likelihood')} | Impact: {r.get('impact')}  \nMitigation: {r.get('mitigation')}")
    lines.append("\n## Open Questions")
    lines += [f"- {q}" for q in est.get("open_questions", []) if q.strip() != "?"]
    return "\n".join(lines)

col_a, col_b = st.columns(2)
with col_a:
    st.download_button("⬇ JSON", data=json.dumps(est, indent=2),
                       file_name="estimate.json", mime="application/json")
with col_b:
    st.download_button("⬇ Markdown", data=build_markdown_report(est),
                       file_name="estimate.md", mime="text/markdown")

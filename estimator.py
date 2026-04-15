import json
import re
import logging
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ── Configuration ─────────────────────────────────────────────────────────────
# load_dotenv() is called here as a convenience fallback for running
# estimator.py directly or in tests. The canonical call lives in app.py.
load_dotenv()

PROMPTS_DIR       = Path(__file__).parent / "prompts"
MODEL             = "claude-opus-4-5"
MAX_TOKENS        = 8096
SCORECARD_WEIGHTS = [25, 20, 25, 15, 15]  # scope, team, integration, timeline, assumptions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Valid enum values ─────────────────────────────────────────────────────────
VALID_SIZES = {"S", "M", "L", "XL"}
VALID_HML        = {"Low", "Medium", "High"}
VALID_RAID_TYPES = {"R", "A", "I", "D"}
VALID_RAID_GRADE = {"H", "M", "L"}

# Normalisation maps — catches common model drift before hard rejection
SIZE_ALIASES: dict[str, str] = {
    "small": "S", "s": "S",
    "medium": "M", "med": "M", "m": "M",
    "large": "L", "l": "L",
    "extra large": "XL", "extra-large": "XL", "xl": "XL", "extralarge": "XL",
}
HML_ALIASES: dict[str, str] = {
    "low": "Low", "lo": "Low",
    "medium": "Medium", "med": "Medium", "moderate": "Medium",
    "high": "High", "hi": "High", "critical": "High", "severe": "High",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text()


def clean_json_response(text: str) -> str:
    """Strip markdown fences and preamble prose if model wraps response."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*",     "", text)
    text = re.sub(r"\s*```$",     "", text)
    # Strip any prose before the first {
    brace = text.find("{")
    if brace > 0:
        logger.warning(f"Stripped {brace} chars of preamble prose before JSON")
        text = text[brace:]
    # Strip any prose after the last }
    rbrace = text.rfind("}")
    if rbrace != -1 and rbrace < len(text) - 1:
        text = text[:rbrace + 1]
    return text.strip()


# ── Auto-correction ───────────────────────────────────────────────────────────
def normalise_size(val) -> str:
    """Normalise a story size to a valid enum value, with alias fallback."""
    if val in VALID_SIZES:
        return val
    if isinstance(val, str):
        normalised = SIZE_ALIASES.get(val.lower().strip())
        if normalised:
            logger.warning(f"Auto-corrected size '{val}' -> '{normalised}'")
            return normalised
    logger.warning(f"Unknown size '{val}', defaulting to 'M'")
    return "M"


def normalise_hml(val, field: str) -> str:
    """Normalise a Low/Medium/High field, with alias fallback."""
    if val in VALID_HML:
        return val
    if isinstance(val, str):
        normalised = HML_ALIASES.get(val.lower().strip())
        if normalised:
            logger.warning(f"Auto-corrected {field} '{val}' -> '{normalised}'")
            return normalised
    logger.warning(f"Unknown {field} '{val}', defaulting to 'Medium'")
    return "Medium"


def auto_correct(data: dict) -> dict:
    """
    Walk the parsed estimate and fix common model drift in-place:
      - Normalise size / likelihood / impact / confidence level enums
      - Ensure all array fields are actually arrays
      - Recalculate total_fte from roles
      - Recalculate scorecard overall_pct and enforce level consistency
      - Strip placeholder '?' entries from open_questions
    """
    # Scope breakdown
    for epic in data.get("scope_breakdown", []):
        if not isinstance(epic.get("stories"), list):
            epic["stories"] = []
        for story in epic["stories"]:
            story["size"]  = normalise_size(story.get("size", "M"))
            story["notes"] = str(story.get("notes") or "")
            # Normalise model-generated RAID items
            if not isinstance(story.get("raid"), list):
                story["raid"] = []
            cleaned_raid = []
            for item in story["raid"]:
                t = str(item.get("type", "")).upper().strip()
                p = str(item.get("prob", "M")).upper().strip()
                i = str(item.get("impact", "M")).upper().strip()
                d = str(item.get("description", "")).strip()
                if t not in VALID_RAID_TYPES:
                    logger.warning(f"Skipping RAID item with invalid type '{t}'")
                    continue
                if p not in VALID_RAID_GRADE:
                    p = "M"
                if i not in VALID_RAID_GRADE:
                    i = "M"
                if d:
                    cleaned_raid.append({"type": t, "prob": p, "impact": i, "description": d})
            story["raid"] = cleaned_raid

    # Timeline
    tl = data.get("timeline", {})
    if not isinstance(tl.get("assumptions"), list):
        tl["assumptions"] = []

    # Resourcing
    res = data.get("resourcing", {})
    if not isinstance(res.get("roles"), list):
        res["roles"] = []
    if not isinstance(res.get("red_flags"), list):
        res["red_flags"] = []
    calculated_fte = sum(float(r.get("fte", 0)) for r in res["roles"])
    if abs(calculated_fte - float(res.get("total_fte", 0))) > 0.01:
        logger.warning(
            f"total_fte mismatch: model said {res.get('total_fte')}, "
            f"calculated {calculated_fte} — using calculated value"
        )
        res["total_fte"] = calculated_fte

    # Risks
    for risk in data.get("risks", []):
        risk["likelihood"] = normalise_hml(risk.get("likelihood", "Medium"), "likelihood")
        risk["impact"]     = normalise_hml(risk.get("impact",     "Medium"), "impact")

    # Confidence
    conf = data.get("confidence", {})
    conf["level"] = normalise_hml(conf.get("level", "Medium"), "confidence level")
    if not isinstance(conf.get("what_would_increase_confidence"), list):
        conf["what_would_increase_confidence"] = []

    # Scorecard — recalculate overall_pct and enforce level consistency
    sc = data.get("confidence_scorecard")
    if sc and isinstance(sc.get("dimensions"), list) and len(sc["dimensions"]) == 5:
        scores = []
        for i, dim in enumerate(sc["dimensions"]):
            s = dim.get("score", 5)
            if not isinstance(s, int):
                s = 5
            s = max(0, min(10, s))
            dim["score"]  = s
            dim["max"]    = 10
            dim["weight"] = SCORECARD_WEIGHTS[i]
            scores.append(s)
        calculated_pct = round(
            sum(s * w for s, w in zip(scores, SCORECARD_WEIGHTS)) / 10
        )
        if sc.get("overall_pct") != calculated_pct:
            logger.warning(
                f"Recalculated overall_pct: {sc.get('overall_pct')} -> {calculated_pct}"
            )
            sc["overall_pct"] = calculated_pct
        expected_level = (
            "High" if calculated_pct >= 70
            else ("Medium" if calculated_pct >= 45 else "Low")
        )
        if conf.get("level") != expected_level:
            logger.warning(
                f"Corrected confidence level: {conf.get('level')} -> {expected_level}"
            )
            conf["level"] = expected_level
    elif not sc:
        data["confidence_scorecard"] = {"overall_pct": 0, "dimensions": []}

    # Open questions — strip placeholder entries
    if not isinstance(data.get("open_questions"), list):
        data["open_questions"] = []
    data["open_questions"] = [
        q for q in data["open_questions"]
        if isinstance(q, str) and q.strip() and q.strip() != "?"
    ]

    return data


# ── Validation ────────────────────────────────────────────────────────────────
def validate_estimate(data: dict) -> list[str]:
    """
    Returns a list of validation errors after auto-correction has run.
    An empty list means the estimate is structurally clean.
    """
    errors: list[str] = []

    # Required top-level fields
    required = [
        "project_title", "summary", "scope_breakdown",
        "timeline", "resourcing", "risks", "confidence", "open_questions",
    ]
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: '{field}'")

    # Scope
    for ei, epic in enumerate(data.get("scope_breakdown", [])):
        if not epic.get("epic"):
            errors.append(f"scope_breakdown[{ei}]: missing 'epic' name")
        for si, story in enumerate(epic.get("stories", [])):
            if story.get("size") not in VALID_SIZES:
                errors.append(
                    f"scope_breakdown[{ei}].stories[{si}]: "
                    f"invalid size '{story.get('size')}' after normalisation"
                )
            if not isinstance(story.get("raid"), list):
                errors.append(
                    f"scope_breakdown[{ei}].stories[{si}]: "
                    f"'raid' must be an array, got '{type(story.get('raid')).__name__}'"
                )

    # Timeline
    tl  = data.get("timeline", {})
    opt = tl.get("optimistic_weeks")
    pes = tl.get("pessimistic_weeks")
    for field in ["optimistic_weeks", "realistic_weeks", "pessimistic_weeks"]:
        if not isinstance(tl.get(field), (int, float)):
            errors.append(f"timeline.{field} must be a number, got '{tl.get(field)}'")
    if isinstance(opt, (int, float)) and isinstance(pes, (int, float)) and opt > pes:
        errors.append("timeline: optimistic_weeks is greater than pessimistic_weeks")

    # Risks
    for ri, risk in enumerate(data.get("risks", [])):
        for field in ["likelihood", "impact"]:
            if risk.get(field) not in VALID_HML:
                errors.append(f"risks[{ri}].{field}: invalid value '{risk.get(field)}'")

    # Confidence
    conf = data.get("confidence", {})
    if conf.get("level") not in VALID_HML:
        errors.append(f"confidence.level: invalid value '{conf.get('level')}'")

    # Scorecard
    sc = data.get("confidence_scorecard", {})
    if not sc:
        errors.append("Missing confidence_scorecard")
    else:
        pct = sc.get("overall_pct")
        if not isinstance(pct, int) or not (0 <= pct <= 100):
            errors.append(
                f"confidence_scorecard.overall_pct must be int 0-100, got '{pct}'"
            )
        dims = sc.get("dimensions", [])
        if len(dims) != 5:
            errors.append(
                f"confidence_scorecard must have 5 dimensions, got {len(dims)}"
            )
        for di, dim in enumerate(dims):
            s = dim.get("score")
            if not isinstance(s, int) or not (0 <= s <= 10):
                errors.append(f"scorecard dim {di} score must be int 0-10, got '{s}'")
            if di < len(SCORECARD_WEIGHTS) and dim.get("weight") != SCORECARD_WEIGHTS[di]:
                errors.append(
                    f"scorecard dim {di} weight should be {SCORECARD_WEIGHTS[di]}, "
                    f"got '{dim.get('weight')}'"
                )

    return errors


# ── Private API helper ────────────────────────────────────────────────────────
def _call_api(user_message: str, log_label: str) -> dict:
    """
    Send a single request to the Claude API, parse and validate the response.

    This is the single point of API interaction for both estimate_project()
    and followup_estimate(). Changes to model, token limits, retry logic,
    or error handling only need to happen here.

    Raises ValueError if the response cannot be parsed as valid JSON.
    Attaches _validation_warnings to the result dict if non-fatal issues
    remain after auto-correction.
    """
    client        = anthropic.Anthropic()
    system_prompt = load_prompt("system_prompt.txt")

    logger.info(f"Calling Claude API: {log_label}")
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw     = message.content[0].text
    cleaned = clean_json_response(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        if len(cleaned) > 7000:
            raise ValueError(
                "The estimate was too large to complete in one response. "
                "Try a more focused brief — describe the core team, the key "
                "integrations, and the main deadline."
            ) from e
        raise ValueError(
            f"Model returned invalid JSON: {e}\n\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        ) from e

    data   = auto_correct(data)
    errors = validate_estimate(data)

    if errors:
        logger.warning(
            f"{log_label} — {len(errors)} validation issue(s) after auto-correct:"
        )
        for err in errors:
            logger.warning(f"  * {err}")
        data["_validation_warnings"] = errors
    else:
        logger.info(f"{log_label} — passed validation.")

    return data


# ── Public API ────────────────────────────────────────────────────────────────
def estimate_project(brief: str) -> dict:
    """
    Takes a freeform project brief and returns a validated, corrected
    estimation report as a dict.
    """
    user_message = f"Please estimate the following project:\n\n{brief}"
    return _call_api(user_message, log_label="estimate_project")


def followup_estimate(previous_estimate: dict, followup_question: str) -> dict:
    """
    Re-estimates based on a change scenario (e.g. 'what if we cut the team in half?').
    Returns an updated estimate dict with a 'changes' key showing diffs.
    """
    # Strip internal metadata keys before sending back to the model
    clean_previous = {
        k: v for k, v in previous_estimate.items()
        if not k.startswith("_")
    }

    followup_template = load_prompt("followup_prompt.txt")
    user_message = followup_template.replace(
        "{previous_estimate}", json.dumps(clean_previous, indent=2)
    ).replace(
        "{followup}", followup_question
    )

    return _call_api(user_message, log_label="followup_estimate")

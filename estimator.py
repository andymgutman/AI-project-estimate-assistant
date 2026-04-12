import os
import json
import re
import logging
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()

PROMPTS_DIR = Path(__file__).parent / "prompts"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Valid enum values ─────────────────────────────────────────────────────────
VALID_SIZES = {"S", "M", "L", "XL"}
VALID_HML   = {"Low", "Medium", "High"}

# Normalisation maps — catches common model drift before hard rejection
SIZE_ALIASES = {
    "small": "S", "s": "S",
    "medium": "M", "med": "M", "m": "M",
    "large": "L", "l": "L",
    "extra large": "XL", "extra-large": "XL", "xl": "XL", "extralarge": "XL",
}
HML_ALIASES = {
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
    # Strip ```json ... ``` fences
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
    """Attempt to normalise a story size to a valid value."""
    if val in VALID_SIZES:
        return val
    if isinstance(val, str):
        normalised = SIZE_ALIASES.get(val.lower().strip())
        if normalised:
            logger.warning(f"Auto-corrected size '{val}' → '{normalised}'")
            return normalised
    logger.warning(f"Unknown size '{val}', defaulting to 'M'")
    return "M"

def normalise_hml(val, field: str) -> str:
    """Attempt to normalise a Low/Medium/High field."""
    if val in VALID_HML:
        return val
    if isinstance(val, str):
        normalised = HML_ALIASES.get(val.lower().strip())
        if normalised:
            logger.warning(f"Auto-corrected {field} '{val}' → '{normalised}'")
            return normalised
    logger.warning(f"Unknown {field} '{val}', defaulting to 'Medium'")
    return "Medium"

def auto_correct(data: dict) -> dict:
    """
    Walk the parsed estimate and silently fix common model drift:
    - Normalise size values
    - Normalise likelihood/impact/confidence level values
    - Ensure arrays are arrays, strings are strings
    - Recalculate total_fte from roles
    """
    # Scope breakdown
    for epic in data.get("scope_breakdown", []):
        if not isinstance(epic.get("stories"), list):
            epic["stories"] = []
        for story in epic["stories"]:
            story["size"]  = normalise_size(story.get("size", "M"))
            story["notes"] = str(story.get("notes") or "")

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
    # Recalculate total_fte to catch arithmetic errors
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

    # Open questions
    if not isinstance(data.get("open_questions"), list):
        data["open_questions"] = []
    # Remove placeholder "?" entries that occasionally appear
    data["open_questions"] = [
        q for q in data["open_questions"]
        if isinstance(q, str) and q.strip() and q.strip() != "?"
    ]

    return data

# ── Validation ────────────────────────────────────────────────────────────────
def validate_estimate(data: dict) -> list[str]:
    """
    Returns a list of validation errors after auto-correction has been applied.
    An empty list means the estimate is clean.
    These are errors that auto_correct could not fix.
    """
    errors = []

    # Required top-level fields
    required = [
        "project_title", "summary", "scope_breakdown",
        "timeline", "resourcing", "risks", "confidence", "open_questions"
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

    # Timeline
    tl = data.get("timeline", {})
    for field in ["optimistic_weeks", "realistic_weeks", "pessimistic_weeks"]:
        if not isinstance(tl.get(field), (int, float)):
            errors.append(f"timeline.{field} must be a number, got '{tl.get(field)}'")
    if (isinstance(tl.get("optimistic_weeks"), (int, float)) and
        isinstance(tl.get("pessimistic_weeks"), (int, float)) and
        tl.get("optimistic_weeks", 0) > tl.get("pessimistic_weeks", 0)):
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

    return errors

# ── Core API functions ────────────────────────────────────────────────────────
def estimate_project(brief: str) -> dict:
    """
    Takes a freeform project brief and returns a validated, corrected
    estimation report as a dict.
    """
    client        = anthropic.Anthropic()
    system_prompt = load_prompt("system_prompt.txt")

    logger.info("Calling Claude API for project estimation...")
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Please estimate the following project:\n\n{brief}"
            }
        ]
    )

    raw     = message.content[0].text
    cleaned = clean_json_response(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Model returned invalid JSON: {e}\n\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        )

    data   = auto_correct(data)
    errors = validate_estimate(data)

    if errors:
        logger.warning(f"Validation issues after auto-correct ({len(errors)}):")
        for err in errors:
            logger.warning(f"  • {err}")
        # Surface non-fatal warnings in the estimate itself for transparency
        data["_validation_warnings"] = errors
    else:
        logger.info("Estimate passed validation.")

    return data


def followup_estimate(previous_estimate: dict, followup_question: str) -> dict:
    """
    Re-estimates based on a change scenario.
    Returns updated estimate dict with a 'changes' key showing diffs.
    """
    client            = anthropic.Anthropic()
    system_prompt     = load_prompt("system_prompt.txt")
    followup_template = load_prompt("followup_prompt.txt")

    # Remove internal validation warnings before sending back to model
    clean_previous = {k: v for k, v in previous_estimate.items()
                      if not k.startswith("_")}

    followup_prompt = followup_template.replace(
        "{previous_estimate}", json.dumps(clean_previous, indent=2)
    ).replace(
        "{followup}", followup_question
    )

    logger.info("Calling Claude API for re-estimation...")
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": followup_prompt
            }
        ]
    )

    raw     = message.content[0].text
    cleaned = clean_json_response(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Re-estimation returned invalid JSON: {e}\n\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        )

    data   = auto_correct(data)
    errors = validate_estimate(data)

    if errors:
        logger.warning(f"Re-estimation validation issues ({len(errors)}):")
        for err in errors:
            logger.warning(f"  • {err}")
        data["_validation_warnings"] = errors
    else:
        logger.info("Re-estimation passed validation.")

    return data


# ── Utility functions ─────────────────────────────────────────────────────────
def size_to_days(size: str) -> tuple[int, int]:
    """Returns (min_days, max_days) for a story size label."""
    return {"S": (1, 3), "M": (3, 7), "L": (7, 21), "XL": (21, 60)}.get(size, (1, 3))

def confidence_color(level: str) -> str:
    return {"High": "green", "Medium": "orange", "Low": "red"}.get(level, "gray")

def risk_color(level: str) -> str:
    return {"High": "red", "Medium": "orange", "Low": "green"}.get(level, "gray")

import json
import re
from pathlib import Path

from dotenv import load_dotenv
import anthropic

load_dotenv()

PROMPTS_DIR = Path(__file__).parent / "prompts"

def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text()

def clean_json_response(text: str) -> str:
    """Strip markdown fences if model wraps response in them."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()

def estimate_project(brief: str) -> dict:
    """
    Takes a freeform or structured project brief and returns
    a structured estimation report as a dict.
    """
    client = anthropic.Anthropic()
    system_prompt = load_prompt("system_prompt.txt")

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Please estimate the following project:\n\n{brief}"
            }
        ]
    )

    raw = message.content[0].text
    cleaned = clean_json_response(raw)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model returned invalid JSON: {e}\n\nRaw response:\n{raw}")

def followup_estimate(previous_estimate: dict, followup_question: str) -> dict:
    """
    Re-estimates based on a change scenario (e.g., 'what if we cut the team in half?').
    Returns updated estimate dict with a 'changes' key showing diffs.
    """
    client = anthropic.Anthropic()
    system_prompt = load_prompt("system_prompt.txt")
    followup_template = load_prompt("followup_prompt.txt")

    followup_prompt = followup_template.replace(
        "{previous_estimate}", json.dumps(previous_estimate, indent=2)
    ).replace(
        "{followup}", followup_question
    )

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": followup_prompt
            }
        ]
    )

    raw = message.content[0].text
    cleaned = clean_json_response(raw)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model returned invalid JSON: {e}\n\nRaw response:\n{raw}")

def size_to_days(size: str) -> tuple[int, int]:
    """Returns (min_days, max_days) for a story size label."""
    return {"S": (1, 3), "M": (3, 7), "L": (7, 21), "XL": (21, 60)}.get(size, (1, 3))

def confidence_color(level: str) -> str:
    return {"High": "green", "Medium": "orange", "Low": "red"}.get(level, "gray")

def risk_color(level: str) -> str:
    return {"High": "red", "Medium": "orange", "Low": "green"}.get(level, "gray")

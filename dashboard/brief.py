"""The plain-language brief at the top of the Home and sector pages.

Pure functions over analytics rows, so the copy is unit-tested like data.
Copy rules (plan, "Design direction"): plain verbs, sentence case, digits for
counts except scraper counts one..nine, and an honest empty state."""
from __future__ import annotations

from typing import List, Optional

_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
          6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}


def _join(names: List[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def new_roles_sentence(new_this_week: int, new_previous_week: int) -> str:
    if new_this_week == 0:
        return "No new roles have landed this week yet."
    roles = "role" if new_this_week == 1 else "roles"
    diff = new_this_week - new_previous_week
    if diff > 0:
        tail = f"{diff} more than last week"
    elif diff < 0:
        tail = f"{-diff} fewer than last week"
    else:
        tail = "the same as last week"
    return f"{new_this_week} new {roles} landed this week, {tail}."


def skills_sentence(top_skills: List[dict], window_label: str) -> Optional[str]:
    names = [r["skill"] for r in top_skills[:3]]
    if not names:
        return None
    verb = "leads" if len(names) == 1 else "lead"
    return f"{_join(names)} {verb} demand {window_label}."


def companies_sentence(velocity_this_week: List[dict]) -> Optional[str]:
    busiest = sorted((r for r in velocity_this_week if r["new_in_window"] > 0),
                     key=lambda r: (-r["new_in_window"], r["company"]))[:2]
    if not busiest:
        return None
    return f"{_join([r['company'] for r in busiest])} posted the most."


def health_sentence(companies_failing: int) -> Optional[str]:
    if companies_failing == 0:
        return None
    number = _WORDS.get(companies_failing, str(companies_failing))
    verb = "scraper needs" if companies_failing == 1 else "scrapers need"
    return f"{number} {verb} attention."


def compose_brief(overview: dict, top_skills: List[dict], velocity_this_week: List[dict],
                  window_label: str) -> dict:
    return {
        "lead": new_roles_sentence(overview["new_this_week"], overview["new_previous_week"]),
        "skills": skills_sentence(top_skills, window_label),
        "companies": companies_sentence(velocity_this_week),
        "health": health_sentence(overview["companies_failing"]),
    }

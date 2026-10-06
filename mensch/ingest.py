"""Learn from chat logs: extract question/answer pairs that employees exchanged."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Employee, KnowledgeItem

_LINE_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?([^:\[\]\n]{1,60}?)\s*:\s+(.+)$")


def parse_chat(text: str) -> list[tuple[str, str]]:
    """Parse lines like ``Alice: message`` or ``[10:31] Alice: message``.

    Lines that don't start with an author continue the previous message.
    """
    messages: list[tuple[str, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = _LINE_RE.match(raw)
        if m:
            messages.append((m.group(1).strip(), m.group(2).strip()))
        elif messages:
            author, msg = messages[-1]
            messages[-1] = (author, f"{msg}\n{raw.strip()}")
    return messages


def _is_question(msg: str) -> bool:
    return "?" in msg


def extract_qa(messages: list[tuple[str, str]]) -> list[tuple[str, str, str, str]]:
    """Return (asker, question, answerer, answer) tuples.

    A question is a message containing '?'; its answer is the next run of
    consecutive messages written by someone else.
    """
    pairs = []
    i = 0
    while i < len(messages):
        asker, msg = messages[i]
        if not _is_question(msg):
            i += 1
            continue
        j = i + 1
        while j < len(messages) and messages[j][0] == asker:
            j += 1
        if j >= len(messages):
            break
        answerer = messages[j][0]
        parts = []
        k = j
        while k < len(messages) and messages[k][0] == answerer:
            parts.append(messages[k][1])
            k += 1
        answer = "\n".join(parts)
        if not (_is_question(answer) and len(answer) < 60):
            pairs.append((asker, msg, answerer, answer))
        i = k
    return pairs


def match_employee(name: str, employees: list[Employee]) -> Employee | None:
    n = name.strip().lower()
    for e in employees:
        if e.name.lower() == n or e.email.lower() == n:
            return e
    first_name_matches = [e for e in employees if e.name.lower().split()[0] == n]
    return first_name_matches[0] if len(first_name_matches) == 1 else None


def ingest_chat(session: Session, text: str) -> dict:
    employees = list(session.scalars(select(Employee)))
    pairs = extract_qa(parse_chat(text))
    unknown: set[str] = set()
    created = []
    for asker_name, question, answerer_name, answer in pairs:
        asker = match_employee(asker_name, employees)
        answerer = match_employee(answerer_name, employees)
        for name, emp in ((asker_name, asker), (answerer_name, answerer)):
            if emp is None:
                unknown.add(name)
        item = KnowledgeItem(
            question=question,
            answer=answer,
            source="chat",
            asked_by_id=asker.id if asker else None,
            answered_by_id=answerer.id if answerer else None,
        )
        session.add(item)
        created.append(item)
    session.commit()
    return {"created": created, "unknown_authors": sorted(unknown)}

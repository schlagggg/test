"""The "who knows what" map, built from skills, answers given, and private notes."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Employee, KnowledgeItem, PrivateNote
from .text import BM25, SurfaceForms, tokenize

WEIGHTS = {"skill": 3.0, "answer": 2.0, "note_title": 2.0, "note": 1.0, "role": 1.0}
REASONS = {
    "skill": "lists it as a skill",
    "answer": "has answered related questions",
    "note_title": "keeps workflow notes on it",
    "note": "keeps workflow notes on it",
    "role": "works on it in their role/team",
}


@dataclass
class Profile:
    employee: Employee
    terms: Counter = field(default_factory=Counter)
    evidence: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def build_profiles(session: Session) -> tuple[list[Profile], SurfaceForms]:
    employees = session.scalars(select(Employee).order_by(Employee.id)).all()
    profiles = {e.id: Profile(e) for e in employees}
    forms = SurfaceForms()

    def add(employee_id: int | None, text: str, kind: str) -> None:
        profile = profiles.get(employee_id)
        if profile is None or not text:
            return
        forms.add(text)
        for term in tokenize(text):
            profile.terms[term] += WEIGHTS[kind]
            profile.evidence[term].add(kind)

    for e in employees:
        add(e.id, " ".join(e.skill_list), "skill")
        add(e.id, f"{e.title} {e.team}", "role")
    for k in session.scalars(select(KnowledgeItem).where(KnowledgeItem.answered_by_id.is_not(None))):
        add(k.answered_by_id, k.question, "answer")
        add(k.answered_by_id, k.answer, "answer")
    for n in session.scalars(select(PrivateNote)):
        add(n.owner_id, n.title, "note_title")
        add(n.owner_id, n.body, "note")
    return list(profiles.values()), forms


def find_experts(session: Session, text: str, exclude_ids: set[int] = frozenset(), limit: int = 3) -> list[dict]:
    profiles, forms = build_profiles(session)
    query = tokenize(text)
    if not profiles or not query:
        return []
    bm25 = BM25([p.terms for p in profiles])
    results = []
    for i, score in bm25.rank(query):
        profile = profiles[i]
        if profile.employee.id in exclude_ids:
            continue
        matched = [t for t in dict.fromkeys(query) if t in profile.terms]
        kinds = {k for t in matched for k in profile.evidence[t]}
        reasons = list(dict.fromkeys(REASONS[k] for k in ("skill", "answer", "note_title", "note", "role") if k in kinds))
        results.append(
            {
                "employee": profile.employee,
                "score": round(score, 3),
                "matched_topics": [forms.get(t) for t in matched],
                "reasons": reasons,
            }
        )
        if len(results) >= limit:
            break
    return results


def expertise_map(session: Session, topics_per_person: int = 8, max_topics: int = 40) -> dict:
    profiles, forms = build_profiles(session)
    bm25 = BM25([p.terms for p in profiles])
    people = []
    topic_people: dict[str, list[tuple[float, Employee]]] = defaultdict(list)
    for p in profiles:
        weighted = {t: w * bm25.idf(t) for t, w in p.terms.items()}
        top = sorted(weighted.items(), key=lambda x: -x[1])[:topics_per_person]
        people.append({"employee": p.employee, "topics": [forms.get(t) for t, _ in top]})
        for t, w in top:
            topic_people[t].append((w, p.employee))
    ranked_topics = sorted(topic_people.items(), key=lambda x: -sum(w for w, _ in x[1]))[:max_topics]
    topics = [
        {
            "topic": forms.get(t),
            "people": [{"id": e.id, "name": e.name} for _, e in sorted(entries, key=lambda x: -x[0])],
        }
        for t, entries in ranked_topics
    ]
    return {"people": people, "topics": topics}

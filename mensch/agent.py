"""The agent: answer from memory / private notes, or find the right colleague and ask them."""

import json
import os
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .expertise import find_experts
from .llm import synthesize_answer
from .models import Employee, ExpertRequest, KnowledgeItem, PrivateNote, Question
from .text import BM25, split_passages, tokenize

CONFIDENCE_THRESHOLD = float(os.environ.get("MENSCH_CONFIDENCE_THRESHOLD", "0.6"))
RELATED_THRESHOLD = 0.3
EXCERPT_LINES = 6


def _note_excerpt(note: PrivateNote, query: list[str]) -> str:
    """The most relevant part of a private note — never the whole note."""
    passages = split_passages(note.body)
    if not passages:
        return ""
    q = set(query)
    overlaps = [len(q & set(tokenize(p))) for p in passages]
    best = max(range(len(passages)), key=lambda i: (overlaps[i], -i))
    return "\n".join(passages[best : best + EXCERPT_LINES])


def search(session: Session, text: str, limit: int = 5) -> list[dict]:
    """Rank remembered Q&A and private notes against a question."""
    query = tokenize(text)
    if not query:
        return []
    items = list(session.scalars(select(KnowledgeItem)))
    notes = list(session.scalars(select(PrivateNote)))
    docs: list[Counter] = []
    for k in items:
        docs.append(Counter(tokenize(k.question) * 2 + tokenize(k.answer)))
    for n in notes:
        docs.append(Counter(tokenize(n.title) * 2 + tokenize(n.body)))
    bm25 = BM25(docs)
    results = []
    for i, score in bm25.rank(query)[: limit * 2]:
        coverage = bm25.coverage(query, i)
        if i < len(items):
            k = items[i]
            who = k.answered_by.name if k.answered_by else "a colleague"
            results.append(
                {
                    "kind": "memory",
                    "id": k.id,
                    "person_id": k.answered_by_id,
                    "person": k.answered_by.name if k.answered_by else None,
                    "label": f"Previously answered by {who}: “{k.question}”",
                    "snippet": k.answer,
                    "pointers": k.pointers,
                    "coverage": round(coverage, 3),
                    "score": round(score, 3),
                }
            )
        else:
            n = notes[i - len(items)]
            results.append(
                {
                    "kind": "private_note",
                    "id": n.id,
                    "person_id": n.owner_id,
                    "person": n.owner.name,
                    "label": f"{n.owner.name}'s private workflow notes",
                    "snippet": _note_excerpt(n, query),
                    "pointers": "",
                    "coverage": round(coverage, 3),
                    "score": round(score, 3),
                }
            )
    results.sort(key=lambda r: (-r["coverage"], -r["score"]))
    return results[:limit]


def _public_source(s: dict) -> dict:
    # Never expose private note ids; the snippet is the only part of a note others see.
    out = {k: s[k] for k in ("kind", "person_id", "person", "label", "snippet", "pointers", "coverage")}
    if s["kind"] == "memory":
        out["id"] = s["id"]
    return out


def _compose_answer(sources: list[dict]) -> str:
    best = sources[0]
    answer = best["snippet"]
    if best.get("pointers"):
        answer += f"\n\nMore info: {best['pointers']}"
    return answer


def _create_request(session: Session, question: Question, expert: Employee, reason: str) -> ExpertRequest:
    req = ExpertRequest(question=question, expert_id=expert.id, reason=reason)
    session.add(req)
    question.status = "routed"
    return req


def route_question(session: Session, question: Question, related: list[dict] | None = None) -> ExpertRequest | None:
    """Ask the best-matching colleague who hasn't been asked yet."""
    exclude = {question.asker_id} | {r.expert_id for r in question.requests}
    experts = find_experts(session, question.text, exclude_ids=exclude, limit=1)
    if experts:
        best = experts[0]
        topics = ", ".join(best["matched_topics"][:4])
        reason = f"Matches on {topics}: {'; '.join(best['reasons'])}." if topics else "Best available match."
        return _create_request(session, question, best["employee"], reason)
    for s in related or []:
        if s["person_id"] and s["person_id"] not in exclude:
            expert = session.get(Employee, s["person_id"])
            return _create_request(session, question, expert, "Wrote something related to this question.")
    question.status = "unanswered"
    return None


def ask(session: Session, asker: Employee, text: str) -> Question:
    question = Question(asker_id=asker.id, text=text.strip(), status="unanswered")
    session.add(question)
    results = search(session, text)
    confidence = results[0]["coverage"] if results else 0.0
    useful = [r for r in results if r["coverage"] >= RELATED_THRESHOLD]

    answer = None
    if useful and confidence >= CONFIDENCE_THRESHOLD:
        llm_answer = synthesize_answer(text, useful[:3])
        if llm_answer == "":
            confidence = min(confidence, RELATED_THRESHOLD)
        else:
            answer = llm_answer or _compose_answer(useful)

    question.confidence = confidence
    question.sources_json = json.dumps([_public_source(s) for s in useful[:3]])
    if answer is not None and confidence >= CONFIDENCE_THRESHOLD:
        question.status = "answered"
        question.answer = answer
    else:
        route_question(session, question, related=useful)
    session.commit()
    session.refresh(question)
    return question


def escalate(session: Session, question: Question) -> ExpertRequest | None:
    """The asker wants a human answer anyway; prefer the author of the source the agent used."""
    if any(r.status == "pending" for r in question.requests):
        return None
    exclude = {question.asker_id} | {r.expert_id for r in question.requests}
    req = None
    for s in json.loads(question.sources_json or "[]"):
        if s.get("person_id") and s["person_id"] not in exclude:
            expert = session.get(Employee, s["person_id"])
            req = _create_request(session, question, expert, "Wrote the source the agent's answer was based on.")
            break
    if req is None:
        req = route_question(session, question)
    session.commit()
    return req


def answer_request(session: Session, req: ExpertRequest, answer: str, pointers: str = "") -> None:
    now = datetime.now(timezone.utc)
    req.status, req.answer, req.pointers, req.answered_at = "answered", answer.strip(), pointers.strip(), now
    q = req.question
    q.status, q.answer, q.pointers, q.answered_by_id = "expert_answered", req.answer, req.pointers, req.expert_id
    for other in q.requests:
        if other.id != req.id and other.status == "pending":
            other.status = "closed"
    session.add(
        KnowledgeItem(
            question=q.text,
            answer=req.answer,
            pointers=req.pointers,
            source="expert",
            asked_by_id=q.asker_id,
            answered_by_id=req.expert_id,
        )
    )
    session.commit()


def decline_request(session: Session, req: ExpertRequest) -> ExpertRequest | None:
    """The colleague doesn't know; the agent moves on to the next best person."""
    req.status = "declined"
    session.flush()
    q = req.question
    nxt = None
    if not any(r.status == "pending" for r in q.requests):
        nxt = route_question(session, q, related=json.loads(q.sources_json or "[]"))
    session.commit()
    return nxt

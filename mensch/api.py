import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import agent
from .db import make_sessionmaker
from .expertise import expertise_map, find_experts
from .ingest import ingest_chat
from .llm import llm_enabled
from .models import Employee, ExpertRequest, KnowledgeItem, PrivateNote, Question, utcnow

STATIC_DIR = Path(__file__).parent / "static"


# ---------- schemas ----------
class EmployeeIn(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    title: str = ""
    team: str = ""
    skills: list[str] = []


class SkillsIn(BaseModel):
    skills: list[str]


class NoteIn(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""


class AskIn(BaseModel):
    question: str = Field(min_length=3)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1)
    pointers: str = ""


class MemoryIn(BaseModel):
    question: str = Field(min_length=3)
    answer: str = Field(min_length=1)
    pointers: str = ""


class ChatIn(BaseModel):
    text: str = Field(min_length=1)


# ---------- serializers ----------
def employee_out(e: Employee | None) -> dict | None:
    if e is None:
        return None
    return {"id": e.id, "name": e.name, "email": e.email, "title": e.title, "team": e.team, "skills": e.skill_list}


def note_out(n: PrivateNote) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def knowledge_out(k: KnowledgeItem) -> dict:
    return {
        "id": k.id,
        "question": k.question,
        "answer": k.answer,
        "pointers": k.pointers,
        "source": k.source,
        "asked_by": employee_out(k.asked_by),
        "answered_by": employee_out(k.answered_by),
        "created_at": k.created_at.isoformat(),
    }


def request_out(r: ExpertRequest, include_question: bool = False) -> dict:
    out = {
        "id": r.id,
        "status": r.status,
        "reason": r.reason,
        "expert": employee_out(r.expert),
        "answer": r.answer,
        "pointers": r.pointers,
        "created_at": r.created_at.isoformat(),
    }
    if include_question:
        out["question"] = {"id": r.question.id, "text": r.question.text, "asker": employee_out(r.question.asker)}
    return out


def question_out(q: Question) -> dict:
    return {
        "id": q.id,
        "text": q.text,
        "status": q.status,
        "answer": q.answer,
        "pointers": q.pointers,
        "confidence": round(q.confidence, 2),
        "sources": json.loads(q.sources_json or "[]"),
        "answered_by": employee_out(q.answered_by),
        "asker": employee_out(q.asker),
        "requests": [request_out(r) for r in q.requests],
        "created_at": q.created_at.isoformat(),
    }


def create_app(database_url: str | None = None, seed_demo: bool | None = None) -> FastAPI:
    app = FastAPI(title="Mensch AI")
    SessionLocal = make_sessionmaker(database_url)
    app.state.sessionmaker = SessionLocal

    if seed_demo is None:
        seed_demo = os.environ.get("MENSCH_SEED_DEMO", "1") != "0"
    if seed_demo:
        from .seed import seed_if_empty

        with SessionLocal() as s:
            seed_if_empty(s)

    def get_session(request: Request):
        with request.app.state.sessionmaker() as session:
            yield session

    def current_user(
        x_user_id: int | None = Header(default=None), session: Session = Depends(get_session)
    ) -> Employee:
        # Demo auth: the UI sends the selected employee's id. Replace with SSO in production.
        user = session.get(Employee, x_user_id) if x_user_id else None
        if user is None:
            raise HTTPException(401, "Unknown user. Send an X-User-Id header.")
        return user

    # ---------- meta ----------
    @app.get("/api/health")
    def health():
        return {"ok": True, "llm": llm_enabled()}

    # ---------- people ----------
    @app.get("/api/employees")
    def list_employees(session: Session = Depends(get_session)):
        return [employee_out(e) for e in session.scalars(select(Employee).order_by(Employee.name))]

    @app.post("/api/employees", status_code=201)
    def create_employee(body: EmployeeIn, session: Session = Depends(get_session)):
        if session.scalar(select(Employee).where(func.lower(Employee.email) == body.email.lower())):
            raise HTTPException(409, "An employee with that email already exists.")
        e = Employee(name=body.name.strip(), email=body.email.strip(), title=body.title, team=body.team,
                     skills=", ".join(s.strip() for s in body.skills if s.strip()))
        session.add(e)
        session.commit()
        return employee_out(e)

    @app.get("/api/me")
    def me(user: Employee = Depends(current_user)):
        return employee_out(user)

    @app.put("/api/me/skills")
    def update_skills(body: SkillsIn, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        user.skills = ", ".join(s.strip() for s in body.skills if s.strip())
        session.add(user)
        session.commit()
        return employee_out(user)

    # ---------- private notes (owner only) ----------
    def own_note(note_id: int, user: Employee, session: Session) -> PrivateNote:
        note = session.get(PrivateNote, note_id)
        if note is None or note.owner_id != user.id:
            raise HTTPException(404, "Note not found.")
        return note

    @app.get("/api/notes")
    def list_notes(user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        notes = session.scalars(
            select(PrivateNote).where(PrivateNote.owner_id == user.id).order_by(PrivateNote.updated_at.desc())
        )
        return [note_out(n) for n in notes]

    @app.post("/api/notes", status_code=201)
    def create_note(body: NoteIn, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        n = PrivateNote(owner_id=user.id, title=body.title.strip(), body=body.body)
        session.add(n)
        session.commit()
        return note_out(n)

    @app.get("/api/notes/{note_id}")
    def get_note(note_id: int, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        return note_out(own_note(note_id, user, session))

    @app.put("/api/notes/{note_id}")
    def update_note(note_id: int, body: NoteIn, user: Employee = Depends(current_user),
                    session: Session = Depends(get_session)):
        n = own_note(note_id, user, session)
        n.title, n.body, n.updated_at = body.title.strip(), body.body, utcnow()
        session.commit()
        return note_out(n)

    @app.delete("/api/notes/{note_id}", status_code=204)
    def delete_note(note_id: int, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        session.delete(own_note(note_id, user, session))
        session.commit()

    # ---------- asking ----------
    @app.post("/api/ask")
    def ask(body: AskIn, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        return question_out(agent.ask(session, user, body.question))

    @app.get("/api/questions")
    def my_questions(user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        qs = session.scalars(select(Question).where(Question.asker_id == user.id).order_by(Question.id.desc()))
        return [question_out(q) for q in qs]

    def own_question(question_id: int, user: Employee, session: Session) -> Question:
        q = session.get(Question, question_id)
        if q is None or q.asker_id != user.id:
            raise HTTPException(404, "Question not found.")
        return q

    @app.get("/api/questions/{question_id}")
    def get_question(question_id: int, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        return question_out(own_question(question_id, user, session))

    @app.post("/api/questions/{question_id}/escalate")
    def escalate(question_id: int, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        q = own_question(question_id, user, session)
        if any(r.status == "pending" for r in q.requests):
            raise HTTPException(409, "A colleague has already been asked.")
        agent.escalate(session, q)
        session.refresh(q)
        return question_out(q)

    # ---------- inbox: questions the agent routed to me ----------
    @app.get("/api/inbox")
    def inbox(user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        reqs = session.scalars(
            select(ExpertRequest).where(ExpertRequest.expert_id == user.id).order_by(ExpertRequest.id.desc())
        )
        return [request_out(r, include_question=True) for r in reqs]

    def own_pending_request(request_id: int, user: Employee, session: Session) -> ExpertRequest:
        r = session.get(ExpertRequest, request_id)
        if r is None or r.expert_id != user.id:
            raise HTTPException(404, "Request not found.")
        if r.status != "pending":
            raise HTTPException(409, f"Request is already {r.status}.")
        return r

    @app.post("/api/requests/{request_id}/answer")
    def answer_request(request_id: int, body: AnswerIn, user: Employee = Depends(current_user),
                       session: Session = Depends(get_session)):
        r = own_pending_request(request_id, user, session)
        agent.answer_request(session, r, body.answer, body.pointers)
        return request_out(r, include_question=True)

    @app.post("/api/requests/{request_id}/decline")
    def decline_request(request_id: int, user: Employee = Depends(current_user),
                        session: Session = Depends(get_session)):
        r = own_pending_request(request_id, user, session)
        nxt = agent.decline_request(session, r)
        return {"declined": request_out(r), "rerouted_to": employee_out(nxt.expert) if nxt else None}

    # ---------- who knows what ----------
    @app.get("/api/experts")
    def experts(q: str, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        return [
            {**{k: v for k, v in x.items() if k != "employee"}, "employee": employee_out(x["employee"])}
            for x in find_experts(session, q, limit=5)
        ]

    @app.get("/api/expertise-map")
    def get_expertise_map(user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        m = expertise_map(session)
        return {
            "people": [{"employee": employee_out(p["employee"]), "topics": p["topics"]} for p in m["people"]],
            "topics": m["topics"],
        }

    # ---------- shared memory ----------
    @app.get("/api/memory")
    def list_memory(q: str | None = None, user: Employee = Depends(current_user),
                    session: Session = Depends(get_session)):
        if q:
            ids = [r["id"] for r in agent.search(session, q, limit=20) if r["kind"] == "memory"]
            items = [session.get(KnowledgeItem, i) for i in ids]
        else:
            items = session.scalars(select(KnowledgeItem).order_by(KnowledgeItem.id.desc()))
        return [knowledge_out(k) for k in items]

    @app.post("/api/memory", status_code=201)
    def add_memory(body: MemoryIn, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        k = KnowledgeItem(question=body.question, answer=body.answer, pointers=body.pointers, source="manual",
                          answered_by_id=user.id)
        session.add(k)
        session.commit()
        return knowledge_out(k)

    @app.post("/api/memory/ingest-chat")
    def ingest(body: ChatIn, user: Employee = Depends(current_user), session: Session = Depends(get_session)):
        result = ingest_chat(session, body.text)
        return {"created": [knowledge_out(k) for k in result["created"]], "unknown_authors": result["unknown_authors"]}

    # ---------- web UI ----------
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


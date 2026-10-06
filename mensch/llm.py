"""Optional LLM answer synthesis. Enabled when OPENAI_API_KEY is set; otherwise the agent is extractive."""

import os

import httpx

SYSTEM_PROMPT = (
    "You are Mensch AI, a company knowledge assistant. Answer the employee's question using ONLY the "
    "sources provided. Be concise and practical (steps if it is a process). If the sources do not "
    "contain the answer, reply with exactly: INSUFFICIENT"
)


def llm_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def synthesize_answer(question: str, sources: list[dict]) -> str | None:
    """Return an answer, "" if the LLM says the sources are insufficient, or None if unavailable."""
    if not llm_enabled() or not sources:
        return None
    context = "\n\n".join(
        f"[Source {i + 1}: {s['label']}]\n{s['snippet']}" for i, s in enumerate(sources)
    )
    try:
        resp = httpx.post(
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": os.environ.get("MENSCH_LLM_MODEL", "gpt-4o-mini"),
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
    return "" if content.upper().startswith("INSUFFICIENT") else content

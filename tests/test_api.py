from conftest import as_user


def test_requires_user(client):
    assert client.get("/api/notes").status_code == 401
    assert client.get("/api/notes", headers={"X-User-Id": "9999"}).status_code == 401


def test_private_notes_are_private(client, users):
    alice, ben = users["alice"], users["ben"]
    note = client.post("/api/notes", json={"title": "Secret recipe", "body": "step one"},
                       headers=as_user(alice)).json()
    assert client.get(f"/api/notes/{note['id']}", headers=as_user(alice)).status_code == 200
    for method in ("get", "delete"):
        assert getattr(client, method)(f"/api/notes/{note['id']}", headers=as_user(ben)).status_code == 404
    assert client.put(f"/api/notes/{note['id']}", json={"title": "x", "body": ""},
                      headers=as_user(ben)).status_code == 404
    assert all(n["title"] != "Secret recipe" for n in client.get("/api/notes", headers=as_user(ben)).json())


def test_agent_answers_from_private_notes_with_excerpt_only(client, users):
    r = client.post("/api/ask", json={"question": "How do I get my travel expenses reimbursed?"},
                    headers=as_user(users["emma"])).json()
    assert r["status"] == "answered"
    assert "Expensify" in r["answer"]
    src = r["sources"][0]
    assert src["kind"] == "private_note" and src["person"] == "Alice Chen"
    assert "id" not in src
    # The unrelated month-end section of Alice's notes is not leaked.
    assert "Month-End" not in r["answer"]


def test_agent_answers_from_chat_memory(client, users):
    r = client.post("/api/ask", json={"question": "How can I get a new monitor?"},
                    headers=as_user(users["carla"])).json()
    assert r["status"] == "answered"
    assert "IT portal" in r["answer"]
    assert r["sources"][0]["kind"] == "memory"


def test_route_to_expert_answer_and_remember(client, users):
    emma, farah = users["emma"], users["farah"]
    q = client.post("/api/ask", json={"question": "How do I sign an NDA with a new vendor?"},
                    headers=as_user(emma)).json()
    assert q["status"] == "routed"
    assert q["requests"][0]["expert"]["name"] == "Farah Nasser"
    assert "nda" in q["requests"][0]["reason"].lower()

    inbox = client.get("/api/inbox", headers=as_user(farah)).json()
    req = next(r for r in inbox if r["question"]["id"] == q["id"])
    assert req["status"] == "pending"
    # Other people can't answer Farah's request.
    assert client.post(f"/api/requests/{req['id']}/answer", json={"answer": "x"},
                       headers=as_user(emma)).status_code == 404

    client.post(f"/api/requests/{req['id']}/answer",
                json={"answer": "Use the mutual NDA template and send it via DocuSign.",
                      "pointers": "Legal Drive > Templates > Mutual NDA"},
                headers=as_user(farah))
    q = client.get(f"/api/questions/{q['id']}", headers=as_user(emma)).json()
    assert q["status"] == "expert_answered"
    assert q["answered_by"]["name"] == "Farah Nasser"
    assert "DocuSign" in q["answer"]

    # Next time, the agent answers from memory without bothering Farah.
    again = client.post("/api/ask", json={"question": "How do I sign an NDA with a vendor?"},
                        headers=as_user(users["david"])).json()
    assert again["status"] == "answered"
    assert "DocuSign" in again["answer"]
    assert "Legal Drive" in again["answer"]


def test_decline_reroutes_to_next_expert(client, users):
    q = client.post("/api/ask", json={"question": "What are the GDPR rules for vendor contracts?"},
                    headers=as_user(users["ben"])).json()
    first = q["requests"][0]
    assert first["expert"]["name"] == "Farah Nasser"
    res = client.post(f"/api/requests/{first['id']}/decline", headers=as_user(users["farah"])).json()
    assert res["rerouted_to"] is not None
    assert res["rerouted_to"]["name"] not in ("Farah Nasser", "Ben Okafor")
    q = client.get(f"/api/questions/{q['id']}", headers=as_user(users["ben"])).json()
    assert [r["status"] for r in q["requests"]] == ["declined", "pending"]


def test_escalate_asks_source_author(client, users):
    q = client.post("/api/ask", json={"question": "How do I deploy to production?"},
                    headers=as_user(users["emma"])).json()
    assert q["status"] == "answered"
    q = client.post(f"/api/questions/{q['id']}/escalate", headers=as_user(users["emma"])).json()
    assert q["status"] == "routed"
    assert q["requests"][0]["expert"]["name"] == "Ben Okafor"
    assert client.post(f"/api/questions/{q['id']}/escalate",
                       headers=as_user(users["emma"])).status_code == 409


def test_unmatched_question_is_unanswered(client):
    new = client.post("/api/employees", json={"name": "Solo", "email": "solo@x.test"}).json()
    # Only the asker could match -> nobody to route to.
    q = client.post("/api/ask", json={"question": "Zyxquv flombertation?"}, headers=as_user(new["id"])).json()
    assert q["status"] == "unanswered"


def test_experts_and_map(client, users):
    experts = client.get("/api/experts", params={"q": "kubernetes deployment"}, headers=as_user(users["emma"])).json()
    assert experts[0]["employee"]["name"] == "Ben Okafor"
    m = client.get("/api/expertise-map", headers=as_user(users["emma"])).json()
    ben = next(p for p in m["people"] if p["employee"]["name"] == "Ben Okafor")
    assert any(t in ben["topics"] for t in ("deploy", "kubernetes", "production"))
    assert m["topics"]


def test_ingest_chat_and_skills_affect_routing(client, users):
    res = client.post("/api/memory/ingest-chat", headers=as_user(users["emma"]), json={
        "text": "Emma: how do we order business cards?\nDavid: through the Moo account, login is in 1Password\nGhost: hi?\nNobody: yes"
    }).json()
    assert len(res["created"]) == 2
    assert res["created"][0]["answered_by"]["name"] == "David Kim"
    assert set(res["unknown_authors"]) == {"Ghost", "Nobody"}

    client.put("/api/me/skills", json={"skills": ["espresso machine"]}, headers=as_user(users["carla"]))
    q = client.post("/api/ask", json={"question": "Who can fix the espresso machine?"},
                    headers=as_user(users["ben"])).json()
    assert q["requests"][0]["expert"]["name"] == "Carla Diaz"

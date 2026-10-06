"""Demo data for a fictional company, Acme Robotics."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ingest import ingest_chat
from .models import Employee, KnowledgeItem, PrivateNote

EMPLOYEES = [
    ("Alice Chen", "alice@acme.test", "Finance Operations Manager", "Finance",
     "expenses, reimbursement, invoices, budget, corporate card"),
    ("Ben Okafor", "ben@acme.test", "DevOps Engineer", "Engineering",
     "deployment, kubernetes, ci/cd, aws, on-call, production"),
    ("Carla Diaz", "carla@acme.test", "People Partner", "People",
     "onboarding, benefits, parental leave, pto, payroll"),
    ("David Kim", "david@acme.test", "Sales Lead", "Sales",
     "salesforce, crm, pricing, discounts, quotes"),
    ("Emma Rossi", "emma@acme.test", "Product Designer", "Design",
     "figma, design system, brand, user research"),
    ("Farah Nasser", "farah@acme.test", "Legal Counsel", "Legal",
     "nda, contracts, vendor agreements, gdpr, compliance"),
]

NOTES = {
    "alice@acme.test": [
        ("Expense reimbursement workflow", """How I process travel & expense reimbursement
1. Employee submits receipts in Expensify within 30 days of the trip (photo is fine).
2. Their manager approves in Expensify; anything above $2,000 also needs my approval.
3. I export approved reports every Thursday and they get reimbursed in the next payroll run.
4. Lost receipt? Fill in the 'missing receipt' form in the Finance Drive folder.
Tip: per-diem for meals while travelling is $75/day, no receipts needed."""),
        ("Month-end close checklist", """Reconcile corporate card statements by the 3rd business day.
Accruals go to the Month-End sheet in the Finance Drive.
Invoices from vendors must be matched to a PO before payment."""),
    ],
    "ben@acme.test": [
        ("How I deploy to production", """Production deployment steps
1. Merge to main; CI builds the container image and runs the test suite.
2. Promote the build to staging with `make promote ENV=staging` and smoke test the dashboard.
3. Post in #deploys, then run `make promote ENV=prod` (requires on-call approval in PagerDuty).
4. Watch the Grafana 'API latency' board for 15 minutes; roll back with `make rollback` if errors spike.
Deploy freeze: no production deploys on Fridays after 2pm."""),
        ("Getting AWS access", """New engineers request AWS access via the IT portal ticket 'Cloud access'.
I approve it and add them to the engineering SSO group; read-only by default, prod write access needs a manager OK."""),
    ],
    "carla@acme.test": [
        ("Onboarding checklist for new hires", """Before day one: send laptop request to IT and add the hire to the HR system (BambooHR).
Day one: benefits enrollment walkthrough, buddy assignment, security training.
Week one: 1:1 with manager, team intro lunch (budget $30/person, expense via Expensify)."""),
        ("Parental leave policy notes", """Parental leave is 16 weeks fully paid for all parents.
Employees should tell their manager and file the leave request in BambooHR at least 30 days before.
Leave can be split into two blocks within the first year."""),
    ],
    "david@acme.test": [
        ("Discount approval process", """Discounts up to 10%: account executive can approve on their own.
10–20%: needs my approval as sales lead — ping me with the Salesforce opportunity link.
Above 20%: needs CFO approval; submit the deal desk form in Salesforce and attach the margin calculation."""),
    ],
    "emma@acme.test": [
        ("Where the design files live", """All production designs live in the Figma team 'Acme Product'.
Design system components are in the 'Acme DS' library — never detach components.
Brand assets (logos, fonts) are in the Brand folder on the shared Drive."""),
    ],
}

MEMORY = [
    ("What is the wifi password for guests at the office?",
     "Guest wifi is 'Acme-Guest'; the password rotates monthly and is posted at the front desk.",
     "Front desk / #office channel", "carla@acme.test"),
    ("How do I book a meeting room?",
     "Use the Rooms calendar in Google Calendar — add the room as a guest to your event.",
     "", "emma@acme.test"),
]

SAMPLE_CHAT = """[09:12] Emma: does anyone know how to get a new monitor for my desk?
[09:14] Ben: open an IT portal ticket under 'Hardware request', they usually deliver within a week
[09:14] Ben: if it's urgent ping #it-help
[10:02] David: who handles renewals of the Salesforce licenses?
[10:05] Alice: that's me, renewals are in March. Ask me before adding seats so I can update the budget.
"""


def seed_if_empty(session: Session) -> bool:
    if session.scalar(select(Employee.id).limit(1)) is not None:
        return False
    by_email = {}
    for name, email, title, team, skills in EMPLOYEES:
        e = Employee(name=name, email=email, title=title, team=team, skills=skills)
        session.add(e)
        by_email[email] = e
    session.flush()
    for email, notes in NOTES.items():
        for title, body in notes:
            session.add(PrivateNote(owner_id=by_email[email].id, title=title, body=body))
    for question, answer, pointers, email in MEMORY:
        session.add(KnowledgeItem(question=question, answer=answer, pointers=pointers, source="manual",
                                  answered_by_id=by_email[email].id))
    session.commit()
    ingest_chat(session, SAMPLE_CHAT)
    return True

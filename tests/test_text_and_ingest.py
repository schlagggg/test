from mensch.ingest import extract_qa, parse_chat
from mensch.text import BM25, tokenize


def test_tokenize_stems_related_forms():
    assert tokenize("renewals")[0] == tokenize("renew")[0]
    assert tokenize("deployment")[0] == tokenize("deploying")[0]
    assert tokenize("expenses reimbursed") == tokenize("expense reimbursement")
    assert tokenize("How do I get the") == []


def test_bm25_coverage():
    bm25 = BM25([tokenize("deploy to production"), tokenize("expense report")])
    assert bm25.rank(tokenize("production deploy"))[0][0] == 0
    assert bm25.coverage(tokenize("production deploy"), 0) == 1.0
    assert bm25.coverage(tokenize("production deploy"), 1) == 0.0


def test_parse_and_extract_chat():
    chat = """[09:00] Ann: where is the style guide?
[09:01] Bob: in the Brand folder
continued on the shared drive
[09:02] Bob: ping me if you can't find it
[09:03] Ann: thanks!
Ann: lunch?
"""
    messages = parse_chat(chat)
    assert messages[1] == ("Bob", "in the Brand folder\ncontinued on the shared drive")
    pairs = extract_qa(messages)
    assert pairs == [
        ("Ann", "where is the style guide?", "Bob",
         "in the Brand folder\ncontinued on the shared drive\nping me if you can't find it")
    ]

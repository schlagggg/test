"""Lightweight text processing: tokenizing, stemming and BM25 ranking (no external deps)."""

import math
import re
from collections import Counter

STOPWORDS = set(
    """
    a about above after again against all also am an and any anyone are as at be because been before being
    below between both but by can could did do does doing done down during each else ever every few for from
    further get gets getting got had has have having he her here hers herself him himself his how hi hey hello
    i if in into is it its itself just know knows let lets like me might more most must my myself need needs
    no nor not now of off on once only or other our ours ourselves out over own please really same she should
    so some someone something such than thank thanks that the their theirs them themselves then there these
    they this those through to too under until up us very want was we were what when where which while who
    whom why will with would you your yours yourself yourselves anybody somebody tell does dont don't im i'm
    way best right usually currently thing things
    """.split()
)

STEM_LENGTH = 6
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")


_SUFFIXES = ("ments", "ment", "ings", "ing", "als", "al", "ed", "es", "s")


def stem(word: str) -> str:
    """Strip a common suffix, then truncate ("renewals" ~ "renew", "deployment" ~ "deploying")."""
    word = word.replace("’", "'")
    if word.endswith("'s"):
        word = word[:-2]
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    else:
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and not word.endswith("ss") and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
    return word[:STEM_LENGTH]


def words(text: str) -> list[str]:
    """Lowercased content words (stopwords removed), unstemmed."""
    out = []
    for w in _TOKEN_RE.findall(text.lower()):
        w = w.replace("’", "'")
        if w in STOPWORDS or len(w) < 2:
            continue
        if w.endswith("'s"):
            w = w[:-2]
        out.append(w)
    return out


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in words(text)]


class SurfaceForms:
    """Remembers the most common original word for each stem, for display."""

    def __init__(self):
        self._forms: dict[str, Counter] = {}

    def add(self, text: str) -> None:
        for w in words(text):
            self._forms.setdefault(stem(w), Counter())[w] += 1

    def get(self, s: str) -> str:
        forms = self._forms.get(s)
        if not forms:
            return s
        # Prefer the shortest of the most common forms ("expense" over "expenses").
        top = forms.most_common(3)
        best_count = top[0][1]
        return min((w for w, c in top if c >= best_count / 2), key=len)


class BM25:
    def __init__(self, docs: list[list[str] | Counter], k1: float = 1.4, b: float = 0.75):
        self.docs = [d if isinstance(d, Counter) else Counter(d) for d in docs]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.n = len(docs)
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        self.k1, self.b = k1, b
        self.df: Counter = Counter()
        for d in self.docs:
            self.df.update(d.keys())

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: list[str], i: int) -> float:
        doc, dl = self.docs[i], self.lengths[i]
        s = 0.0
        for t in set(query):
            tf = doc.get(t, 0)
            if not tf:
                continue
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            s += self.idf(t) * tf * (self.k1 + 1) / denom
        return s

    def coverage(self, query: list[str], i: int) -> float:
        """IDF-weighted share of the query terms that appear in document i (0..1)."""
        terms = set(query)
        if not terms:
            return 0.0
        total = sum(self.idf(t) for t in terms)
        hit = sum(self.idf(t) for t in terms if t in self.docs[i])
        return hit / total if total else 0.0

    def rank(self, query: list[str]) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.n)]
        return sorted([x for x in scored if x[1] > 0], key=lambda x: -x[1])


def split_passages(text: str) -> list[str]:
    """Split note text into lines / sentences suitable for excerpting."""
    passages = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) > 240:
            passages.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", line) if p.strip())
        else:
            passages.append(line)
    return passages

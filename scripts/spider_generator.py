"""Generic, schema-aware SQL generator for the Spider-subset harness.

This is deliberately **separate** from the app's demo generator: the normal app
keeps using the planner/local generator tuned to the demo analytics intents. This
module is used *only* by ``scripts/run_spider_subset.py`` to attempt SQL for
arbitrary Spider databases.

It is a small, honest heuristic — not a learned text-to-SQL model. It inspects a
database's real schema (tables, columns, types, primary keys, foreign keys) and
maps a handful of common Spider phrasings to valid **SELECT-only** SQLite:

  - ``SELECT count(*) FROM t``            ("how many", "number of")
  - ``SELECT avg/min/max/sum(col) FROM t`` (aggregate words + a numeric column)
  - ``SELECT cols FROM t``                 (columns named in the question)
  - ``... WHERE col <op> number``          (numeric comparisons)
  - ``... ORDER BY col [ASC|DESC] [LIMIT]`` (order words, "top N")
  - ``... GROUP BY col``                   ("for each", "per")
  - a single FK join when two tables are referenced

No gold SQL or expected answers are ever consulted. When the heuristic can't find
a target table, it returns ``None`` (an honest non-generation).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

_WORD = re.compile(r"[a-z0-9]+")

_AGG_WORDS = [
    ("average", "AVG"), ("avg", "AVG"), ("mean", "AVG"),
    ("minimum", "MIN"), ("maximum", "MAX"),
    ("total", "SUM"), ("sum", "SUM"),
]
_DESC_WORDS = ("desc", "descending", "highest", "largest", "biggest", "most", "oldest", "greatest", "top", "reverse")
_ASC_WORDS = ("asc", "ascending", "lowest", "smallest", "youngest", "least", "fewest")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    for suf in ("ses", "xes", "zes", "ches", "shes"):
        if word.endswith(suf):
            return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _norm_tokens(name: str) -> list[str]:
    return [_singular(t) for t in _tokens(name.replace("_", " "))]


def _is_numeric(sql_type: str) -> bool:
    t = (sql_type or "").upper()
    return any(k in t for k in ("INT", "REAL", "NUM", "DEC", "FLOA", "DOUB"))


@dataclass
class Column:
    name: str
    type: str
    pk: bool = False


@dataclass
class ForeignKey:
    from_table: str
    from_col: str
    to_table: str
    to_col: str


@dataclass
class SpiderSchema:
    db_id: str
    tables: dict[str, list[Column]] = field(default_factory=dict)
    foreign_keys: list[ForeignKey] = field(default_factory=list)

    @classmethod
    def from_sqlite(cls, db_id: str, db_path: str) -> "SpiderSchema":
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            names = [
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            tables: dict[str, list[Column]] = {}
            fks: list[ForeignKey] = []
            for t in names:
                cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
                # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
                tables[t] = [Column(c[1], (c[2] or ""), bool(c[5])) for c in cols]
                for fk in con.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
                    # id, seq, table, from, to, on_update, on_delete, match
                    fks.append(ForeignKey(t, fk[3], fk[2], fk[4]))
            return cls(db_id=db_id, tables=tables, foreign_keys=fks)
        finally:
            con.close()

    # --- lookup helpers ----------------------------------------------------

    def numeric_columns(self, table: str) -> list[Column]:
        return [c for c in self.tables.get(table, []) if _is_numeric(c.type)]

    def text_columns(self, table: str) -> list[Column]:
        return [c for c in self.tables.get(table, []) if not _is_numeric(c.type)]

    def column_names(self, table: str) -> set[str]:
        return {c.name for c in self.tables.get(table, [])}

    def has_column(self, table: str, col: str) -> bool:
        return col in self.column_names(table)


class SpiderGenerator:
    """Heuristic NL->SQL over a :class:`SpiderSchema`. SELECT-only by construction."""

    def __init__(self, schema: SpiderSchema):
        self.schema = schema

    # --- public API --------------------------------------------------------

    def generate_sql(self, question: str) -> Optional[str]:
        q = question.lower()
        qtokens = set(_singular(t) for t in _tokens(q))

        table = self._find_table(qtokens)
        if table is None:
            return None

        # 1. COUNT — "how many", "number of", "count".
        if re.search(r"\bhow many\b|\bnumber of\b|\bcount\b", q):
            group = self._find_group_column(q, table)
            if group:
                return f'SELECT "{group}", count(*) FROM "{table}" GROUP BY "{group}"'
            return f'SELECT count(*) FROM "{table}"'

        # 2. AGGREGATES — avg/min/max/sum over a numeric column named in the question.
        aggs = self._detect_aggregates(q, table)
        if aggs:
            select = ", ".join(f'{fn}("{col}")' for fn, col in aggs)
            sql = f'SELECT {select} FROM "{table}"'
            where = self._detect_numeric_where(q, table)
            if where:
                sql += f" WHERE {where}"
            return sql

        # 3. SELECT columns (+ optional WHERE / ORDER BY / LIMIT).
        columns = self._mentioned_columns(q, table)
        select = ", ".join(f'"{c}"' for c in columns) if columns else "*"
        sql = f'SELECT {select} FROM "{table}"'
        where = self._detect_numeric_where(q, table)
        if where:
            sql += f" WHERE {where}"
        order = self._detect_order(q, table)
        limit = self._detect_limit(q)
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {limit}"
        return sql

    def target_table(self, question: str) -> Optional[str]:
        """The table this question is about (public; used for repair fallback)."""
        return self._find_table(set(_singular(t) for t in _tokens(question.lower())))

    def fallback_sql(self, question: str) -> Optional[str]:
        """Simplest valid query for the detected table (repair fallback)."""
        table = self.target_table(question)
        return f'SELECT * FROM "{table}"' if table else None

    # --- heuristics --------------------------------------------------------

    def _find_table(self, qtokens: set[str]) -> Optional[str]:
        best: Optional[str] = None
        best_score = 0
        for table in self.schema.tables:
            name_tokens = _norm_tokens(table)
            if not name_tokens:
                continue
            hits = sum(1 for tok in name_tokens if tok in qtokens)
            # Require the (singularized) table name to be referenced.
            if hits == len(name_tokens) and hits > best_score:
                best_score, best = hits, table
        if best is not None:
            return best
        # Fallback: a table one of whose columns is clearly referenced.
        for table, cols in self.schema.tables.items():
            for c in cols:
                ct = _norm_tokens(c.name)
                if ct and all(t in qtokens for t in ct):
                    return table
        return None

    def _mentioned_columns(self, q: str, table: str) -> list[str]:
        # Position each question token (singularized) so we can order columns the
        # way they are named in the question ("names, countries, ages" -> in order).
        qtoks = [(m.start(), _singular(m.group())) for m in _WORD.finditer(q)]
        qset = {tok for _, tok in qtoks}
        found: list[tuple[int, str]] = []
        for c in self.schema.tables[table]:
            ct = _norm_tokens(c.name)
            if ct and all(t in qset for t in ct):
                positions = [pos for pos, tok in qtoks if tok in set(ct)]
                found.append((min(positions) if positions else 0, c.name))
        found.sort(key=lambda x: x[0])
        return [name for _, name in found]

    def _detect_aggregates(self, q: str, table: str) -> list[tuple[str, str]]:
        col = self._first_numeric_column(q, table)
        if not col:
            return []
        hits: list[tuple[int, str]] = []
        for word, fn in _AGG_WORDS:
            pos = q.find(word)
            if pos >= 0:
                hits.append((pos, fn))
        hits.sort(key=lambda x: x[0])
        # De-dupe consecutive identical funcs (e.g. "average"/"avg").
        result: list[tuple[str, str]] = []
        for _, fn in hits:
            if not result or result[-1][0] != fn:
                result.append((fn, col))
        return result

    def _first_numeric_column(self, q: str, table: str) -> Optional[str]:
        qtokens = set(_singular(t) for t in _tokens(q))
        for c in self.schema.numeric_columns(table):
            ct = _norm_tokens(c.name)
            if ct and all(t in qtokens for t in ct) and c.name.lower() not in ("id",):
                return c.name
        return None

    def _find_group_column(self, q: str, table: str) -> Optional[str]:
        # "for each / per / grouped by / in each <col>", or "... in each country".
        if not re.search(r"\bfor each\b|\bper\b|\bgrouped by\b|\beach\b", q):
            return None
        qset = {_singular(x) for x in _tokens(q)}
        fallback: Optional[str] = None
        for c in self.schema.tables[table]:
            ct = _norm_tokens(c.name)
            if ct and all(t in qset for t in ct):
                if not _is_numeric(c.type):
                    return c.name       # prefer a categorical grouping column
                fallback = fallback or c.name
        return fallback

    def _detect_order(self, q: str, table: str) -> Optional[str]:
        if not re.search(r"\border(ed|s)?\b|\bsort(ed)?\b|\bby\b", q):
            # still allow bare superlatives like "the oldest"
            if not any(w in q for w in _DESC_WORDS + _ASC_WORDS):
                return None
        col = self._first_numeric_column(q, table) or self._first_named_column(q, table)
        if not col:
            return None
        direction = "ASC"
        if any(w in q for w in _DESC_WORDS):
            direction = "DESC"
        elif any(w in q for w in _ASC_WORDS):
            direction = "ASC"
        return f'"{col}" {direction}'

    def _first_named_column(self, q: str, table: str) -> Optional[str]:
        cols = self._mentioned_columns(q, table)
        return cols[0] if cols else None

    def _detect_limit(self, q: str) -> Optional[int]:
        m = re.search(r"\b(?:top|first|limit)\s+(\d+)\b", q)
        if m:
            return int(m.group(1))
        return None

    def _detect_numeric_where(self, q: str, table: str) -> Optional[str]:
        col = self._first_numeric_column(q, table)
        if not col:
            return None
        between = re.search(r"\bbetween\s+(\d+)\s+and\s+(\d+)", q)
        gt = re.search(r"\b(?:greater than|more than|above|over|larger than)\s+(\d+)", q)
        lt = re.search(r"\b(?:less than|fewer than|below|under|smaller than)\s+(\d+)", q)
        eq = re.search(r"\b(?:equal to|equals|is)\s+(\d+)\b", q)
        if between:
            return f'"{col}" BETWEEN {between.group(1)} AND {between.group(2)}'
        if gt:
            return f'"{col}" > {gt.group(1)}'
        if lt:
            return f'"{col}" < {lt.group(1)}'
        if eq:
            return f'"{col}" = {eq.group(1)}'
        return None


# --- Full mode: value linking + multi-candidate generation ------------------

_STOP_VALUE_WORDS = {
    "What", "Which", "Who", "How", "Where", "When", "Show", "List", "Find",
    "Give", "Return", "Count", "Name", "Names", "Please", "The", "A", "An",
    "For", "In", "Of", "All", "And", "Or",
}

_SUPERLATIVE_DESC = ("most", "highest", "largest", "biggest", "greatest", "maximum",
                     "oldest", "longest", "top")
_SUPERLATIVE_ASC = ("least", "lowest", "smallest", "fewest", "minimum",
                    "youngest", "shortest")


def _sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def extract_candidate_values(question: str) -> list[str]:
    """Pull likely literal values from a question: quoted strings + proper nouns."""
    values: list[str] = []
    for m in re.finditer(r"'([^']+)'|\"([^\"]+)\"", question):
        values.append(m.group(1) or m.group(2))
    # Title-case runs not at the very start of the sentence.
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*)", question):
        if m.start() == 0:
            continue
        phrase = m.group(1).strip(" .,:;!?")
        if phrase in _STOP_VALUE_WORDS or all(w in _STOP_VALUE_WORDS for w in phrase.split()):
            continue
        values.append(phrase)
    # De-dupe preserving order.
    seen, out = set(), []
    for v in values:
        if v.lower() not in seen and len(v) >= 2:
            seen.add(v.lower())
            out.append(v)
    return out


def link_values(
    question: str, schema: SpiderSchema, conn, prefer_table: Optional[str] = None
) -> list[tuple[str, str, str]]:
    """Return (table, column, db_value) for question values found in text columns.

    Uses a read-only, parameterized, case-insensitive exact lookup with LIMIT —
    a safe database value lookup. Never reads gold SQL or expected results. When
    ``prefer_table`` is given, that table's columns are checked first (a value
    like ``ATO`` may exist in several tables; prefer the queried one).
    """
    order = list(schema.tables)
    if prefer_table in schema.tables:
        order = [prefer_table] + [t for t in order if t != prefer_table]
    links: list[tuple[str, str, str]] = []
    used_values: set[str] = set()
    for value in extract_candidate_values(question):
        for table in order:
            hit = None
            for col in schema.text_columns(table):
                try:
                    row = conn.execute(
                        f'SELECT "{col.name}" FROM "{table}" '
                        f'WHERE "{col.name}" = ? COLLATE NOCASE LIMIT 1',
                        (value,),
                    ).fetchone()
                except sqlite3.Error:
                    continue
                if row and row[0] is not None:
                    hit = (table, col.name, str(row[0]))
                    break
            if hit and value.lower() not in used_values:
                links.append(hit)
                used_values.add(value.lower())
                break
    return links


def build_full_candidates(
    question: str, schema: SpiderSchema, conn, max_candidates: int = 3
) -> list[str]:
    """Ranked SELECT-only candidates using schema + value linking + superlatives."""
    q = question.lower()
    qtokens = {_singular(t) for t in _tokens(q)}
    gen = SpiderGenerator(schema)

    # Detect the base table first (schema-only), then link values preferring it.
    base = gen._find_table(qtokens)
    links = link_values(question, schema, conn, prefer_table=base)
    if base is None and links:
        base = links[0][0]
    if base is None:
        return []

    linked_cols = {c for (t, c, v) in links if t == base}
    where_parts = [f'"{c}" = {_sql_str(v)}' for (t, c, v) in links if t == base]
    numeric_where = gen._detect_numeric_where(q, base)
    if numeric_where:
        where_parts.append(numeric_where)
    where = " AND ".join(where_parts) if where_parts else None

    distinct = ("distinct" in q or "different" in q)
    limit = gen._detect_limit(q)
    candidates: list[str] = []

    def render(select, *, where=where, group=None, order=None, lim=limit, dis=distinct):
        sql = f"SELECT {'DISTINCT ' if dis else ''}{select} FROM \"{base}\""
        if where:
            sql += f" WHERE {where}"
        if group:
            sql += f" GROUP BY {group}"
        if order:
            sql += f" ORDER BY {order}"
        if lim:
            sql += f" LIMIT {lim}"
        return sql

    # 1) COUNT.
    if re.search(r"\bhow many\b|\bnumber of\b|\bcount\b", q):
        grp = gen._find_group_column(q, base)
        if grp:
            candidates.append(render(f'"{grp}", count(*)', group=f'"{grp}"', dis=False))
        candidates.append(render("count(*)", dis=False))
        return _dedupe(candidates)[:max_candidates]

    def _projection() -> str:
        # Columns named in the question, minus those already used as value filters.
        cols = [c for c in gen._mentioned_columns(q, base) if c not in linked_cols]
        return ", ".join(f'"{c}"' for c in cols) if cols else "*"

    # 2) Superlative single row: "... with the most/least <col>", "the oldest ...".
    sup = _superlative(q, gen, base)
    if sup:
        col, direction = sup
        candidates.append(render(_projection(), order=f'"{col}" {direction}', lim=1))

    # 3) Aggregates over a named numeric column.
    aggs = gen._detect_aggregates(q, base)
    if aggs:
        select = ", ".join(f'{fn}("{c}")' for fn, c in aggs)
        candidates.append(render(select, dis=False, order=None, lim=None))

    # 4) Projection select (+ value/numeric WHERE, order, distinct).
    select = _projection()
    order = gen._detect_order(q, base) if re.search(r"\border|sort", q) else None
    candidates.append(render(select, order=order))
    if distinct:
        candidates.append(render(select, order=order, dis=False))  # variant w/o DISTINCT
    if where:
        candidates.append(render(select, where=None, order=order))  # variant w/o filter
    return _dedupe(candidates)[:max_candidates]


def _superlative(q: str, gen: "SpiderGenerator", table: str):
    desc = any(w in q for w in _SUPERLATIVE_DESC)
    asc = any(w in q for w in _SUPERLATIVE_ASC)
    if not (desc or asc):
        return None
    col = gen._first_numeric_column(q, table)
    if not col:
        return None
    return col, ("DESC" if desc else "ASC")


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

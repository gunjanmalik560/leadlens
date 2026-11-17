"""
LeadLens v2 - core logic: question -> SQL -> safety check -> answer.

Used by ask.py (terminal), evaluate.py (accuracy test) and app.py (Streamlit).
"""
import os
import re
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from pathlib import Path

HERE = Path(__file__).parent
try:
    load_dotenv(HERE / ".env")  # always read the .env next to this file
except UnicodeDecodeError:
    pass  # file saved in an odd encoding; the fallback below handles it


def _load_env_fallback(path=HERE / ".env"):
    """Windows editors sometimes save .env as UTF-16 or UTF-8-with-BOM,
    which python-dotenv misreads. Parse it manually in that case."""
    if not path.exists():
        return
    raw = path.read_bytes()
    enc = ("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff"))
           else "utf-8-sig")
    for line in raw.decode(enc, errors="ignore").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if v and not os.getenv(k):
                os.environ[k] = v


_load_env_fallback()

DB_PATH = os.getenv("DB_PATH") or str(HERE / "crm.db")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


def get_client():
    """Works with OpenAI, or any OpenAI-compatible API (set LLM_BASE_URL)."""
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or api_key.startswith("paste-your"):
        raise ValueError(
            f"No API key found. Put LLM_API_KEY=your-key in {HERE / '.env'}")
    base_url = os.getenv("LLM_BASE_URL") or None
    # Retries are handled in call_llm() so a daily-quota error is not retried.
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60)


class DailyQuotaExceeded(RuntimeError):
    pass


def call_llm(client, **kwargs):
    """Call the model, retrying only errors that can succeed on retry.

    - 503 (server busy) and per-minute 429: wait 5, 10, 20, 40 s and retry.
    - Daily-quota 429: stop immediately - retrying would just waste requests.
    """
    import time
    from openai import APIStatusError

    wait = 5
    for attempt in range(5):
        try:
            return client.chat.completions.create(**kwargs)
        except APIStatusError as e:
            text = str(getattr(e.response, "text", "")) + str(e)
            if e.status_code == 429 and ("per day" in text.lower()
                                         or "PerDay" in text):
                raise DailyQuotaExceeded(
                    f"Daily free-tier limit reached for {MODEL}. "
                    "Try again tomorrow or switch LLM_MODEL in .env.") from e
            if e.status_code not in (429, 500, 503) or attempt == 4:
                raise
            print(f"  (API busy, retrying in {wait}s...)")
            time.sleep(wait)
            wait *= 2


# ---------------------------------------------------------------------------
# 1. Describe the database to the model
# ---------------------------------------------------------------------------
def get_schema(db_path=DB_PATH):
    """Return the CREATE TABLE statements, read straight from the database."""
    if not Path(db_path).exists() or Path(db_path).stat().st_size == 0:
        raise FileNotFoundError(
            f"Database not found or empty: {Path(db_path).resolve()}. "
            "Copy crm.db into this folder (or run: python generate_crm.py).")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    con.close()
    return "\n\n".join(r[0] for r in rows)


BUSINESS_NOTES = """
Business rules:
- Open lead statuses: New, Contacted, Qualified, Proposal, Negotiation. Closed: Won, Lost.
- Only closed leads have a row in deals. Revenue = SUM(deals.amount) WHERE outcome = 'Won'.
- Win rate = won deals / all closed deals (from the deals table), as a percentage.
- Amounts are in Indian rupees (INR). Dates are text in YYYY-MM-DD format.
- leads.rep_id NULL means the lead is unassigned.
"""


def build_prompt(question, schema):
    return f"""You write SQLite queries for a sales CRM database.

Schema:
{schema}
{BUSINESS_NOTES}
Rules:
- Return ONE SQLite SELECT query and nothing else: no explanation, no code fences.
- Use only the tables and columns in the schema.
- Use SQLite date functions (strftime, date), not MySQL or PostgreSQL ones.
- SQLite divides integers as integers (7 / 2 = 3). For any ratio, average or
  percentage, multiply by 1.0 first: 1.0 * SUM(x) / SUM(y).
- When the question asks for a top, highest, lowest or most common item, also
  return the value it was ranked by (e.g. the source AND its win rate).
- Give calculated columns short readable names with AS (e.g. AS win_rate_pct).

Question: {question}
SQL:"""


# ---------------------------------------------------------------------------
# 2. Ask the model for SQL
# ---------------------------------------------------------------------------
def clean_sql(text):
    """Strip code fences or a leading 'SQL:' the model sometimes adds."""
    text = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*SQL:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(";").strip() + ";"


def generate_sql(question, client=None):
    client = client or get_client()
    response = call_llm(
        client,
        model=MODEL,
        messages=[{"role": "user", "content": build_prompt(question, get_schema())}],
        temperature=0,  # same question -> same SQL, needed for fair evaluation
    )
    return clean_sql(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# 3. Safety check: read-only queries only
# ---------------------------------------------------------------------------
BLOCKED = ["insert", "update", "delete", "drop", "alter", "create", "replace",
           "attach", "detach", "pragma", "vacuum", "truncate"]


def check_safe(sql):
    """Raise ValueError if the SQL is anything other than a single SELECT."""
    s = sql.strip().rstrip(";").strip()
    lowered = s.lower()
    if ";" in s:
        raise ValueError("Blocked: only one statement is allowed.")
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Blocked: only SELECT queries are allowed.")
    for word in BLOCKED:
        if re.search(rf"\b{word}\b", lowered):
            raise ValueError(f"Blocked: the query contains '{word.upper()}'.")


def run_sql(sql, db_path=DB_PATH):
    check_safe(sql)
    # Second safety layer: open the database in read-only mode.
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, con)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 4. All together
# ---------------------------------------------------------------------------
def ask(question, client=None):
    """Return (sql, dataframe). Raises an error if the SQL is unsafe or fails."""
    sql = generate_sql(question, client)
    return sql, run_sql(sql)

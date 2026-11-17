"""
LeadLens v2 - synthetic CRM database generator.

Creates crm.db (SQLite) with fully fictional data so the project never
uses real client or contact data. Same seed -> same database every time,
which keeps the evaluation set (50 test questions) reproducible.

Usage:  python generate_crm.py            -> writes crm.db
        python generate_crm.py --out x.db
"""
import argparse
import random
import sqlite3
from datetime import date, timedelta

SEED = 42
START = date(2025, 1, 1)
END = date(2026, 10, 31)

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Kabir", "Ishaan", "Karan",
         "Rahul", "Siddharth", "Ananya", "Diya", "Priya", "Sneha", "Kavya", "Riya",
         "Neha", "Pooja", "Meera", "Isha", "Tanvi", "Nikhil", "Varun", "Aman",
         "Simran", "Harsh", "Yash", "Shreya", "Aditi", "Manish"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Mehta", "Kapoor", "Malhotra", "Iyer",
        "Reddy", "Nair", "Joshi", "Agarwal", "Bansal", "Chopra", "Khanna", "Rao",
        "Das", "Bose", "Patel", "Saxena"]
CITIES = {"Delhi": "North", "Gurugram": "North", "Noida": "North", "Jaipur": "North",
          "Mumbai": "West", "Pune": "West", "Ahmedabad": "West",
          "Bangalore": "South", "Chennai": "South", "Hyderabad": "South",
          "Kolkata": "East", "Bhubaneswar": "East"}
INDUSTRIES = ["Retail", "FMCG", "EdTech", "Healthcare", "Real Estate", "Hospitality",
              "Fintech", "Fashion", "Automobile", "Food & Beverage"]
WORDS = ["Nova", "Apex", "Lotus", "Indus", "Saffron", "Peak", "Blue", "Orbit",
         "Vista", "Prime", "Zenith", "Urban", "Royal", "Green", "Silver", "Ganga"]
SUFFIX = ["Pvt Ltd", "Enterprises", "Solutions", "Group", "Industries", "Labs"]
SERVICES = ["Brand Strategy", "Social Media", "Website Design", "Performance Ads",
            "PR Campaign", "Packaging Design", "SEO"]
SERVICE_PRICE = {"Brand Strategy": (300_000, 1_200_000), "Social Media": (60_000, 300_000),
                 "Website Design": (150_000, 600_000), "Performance Ads": (100_000, 500_000),
                 "PR Campaign": (200_000, 800_000), "Packaging Design": (80_000, 400_000),
                 "SEO": (50_000, 250_000)}
SOURCES = ["Website", "Referral", "LinkedIn", "Cold Call", "Event", "Instagram Ads"]
SOURCE_WIN = {"Referral": 0.45, "Event": 0.30, "Website": 0.25, "LinkedIn": 0.22,
              "Instagram Ads": 0.15, "Cold Call": 0.10}   # built-in pattern to discover
STAGES = ["New", "Contacted", "Qualified", "Proposal", "Negotiation"]
ACTIVITY_TYPES = ["Call", "Email", "Meeting", "Demo"]
LOSS_REASONS = ["Budget", "Chose competitor", "No response", "Timing", "Scope mismatch"]

SCHEMA = """
CREATE TABLE sales_reps (
    rep_id     INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    region     TEXT NOT NULL,          -- North / South / East / West
    hire_date  DATE NOT NULL,
    manager_id INTEGER REFERENCES sales_reps(rep_id)   -- NULL for heads
);
CREATE TABLE companies (
    company_id INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    industry   TEXT NOT NULL,
    city       TEXT NOT NULL,
    region     TEXT NOT NULL,
    employees  INTEGER,                -- some NULLs (unknown size)
    created_at DATE NOT NULL
);
CREATE TABLE contacts (
    contact_id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(company_id),
    full_name  TEXT NOT NULL,
    job_title  TEXT,
    email      TEXT,
    phone      TEXT                    -- some NULLs
);
CREATE TABLE campaigns (
    campaign_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    channel     TEXT NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    budget      INTEGER NOT NULL       -- INR
);
CREATE TABLE leads (
    lead_id     INTEGER PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contacts(contact_id),
    rep_id      INTEGER REFERENCES sales_reps(rep_id),  -- NULL = unassigned
    campaign_id INTEGER REFERENCES campaigns(campaign_id),
    source      TEXT NOT NULL,
    service     TEXT NOT NULL,
    status      TEXT NOT NULL,         -- New..Negotiation, Won, Lost
    created_at  DATE NOT NULL,
    closed_at   DATE                   -- set only for Won / Lost
);
CREATE TABLE deals (
    deal_id     INTEGER PRIMARY KEY,
    lead_id     INTEGER NOT NULL UNIQUE REFERENCES leads(lead_id),
    amount      INTEGER NOT NULL,      -- INR
    outcome     TEXT NOT NULL,         -- Won / Lost
    loss_reason TEXT,                  -- NULL when Won
    closed_at   DATE NOT NULL
);
CREATE TABLE activities (
    activity_id   INTEGER PRIMARY KEY,
    lead_id       INTEGER NOT NULL REFERENCES leads(lead_id),
    rep_id        INTEGER REFERENCES sales_reps(rep_id),
    activity_type TEXT NOT NULL,
    activity_date DATE NOT NULL,
    notes         TEXT
);
CREATE INDEX idx_leads_status  ON leads(status);
CREATE INDEX idx_leads_rep     ON leads(rep_id);
CREATE INDEX idx_act_lead      ON activities(lead_id);
"""


def rand_date(rng, a, b):
    return a + timedelta(days=rng.randint(0, (b - a).days))


def build(path):
    rng = random.Random(SEED)
    con = sqlite3.connect(path)
    con.executescript("PRAGMA foreign_keys = ON;" + SCHEMA)

    # --- sales reps: 4 regional heads + 12 reps -------------------------------
    reps, rid = [], 1
    heads = {}
    for region in ["North", "South", "East", "West"]:
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        reps.append((rid, name, region, "2022-04-01", None))
        heads[region] = rid
        rid += 1
    for i in range(12):
        region = ["North", "North", "North", "South", "South", "South",
                  "West", "West", "West", "East", "East", "North"][i]
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        hire = rand_date(rng, date(2022, 6, 1), date(2025, 9, 1)).isoformat()
        reps.append((rid, name, region, hire, heads[region]))
        rid += 1
    con.executemany("INSERT INTO sales_reps VALUES (?,?,?,?,?)", reps)
    reps_by_region = {}
    for r in reps[4:]:
        reps_by_region.setdefault(r[2], []).append(r[0])
    rep_skill = {r[0]: rng.uniform(0.8, 1.25) for r in reps[4:]}  # some reps close better

    # --- companies & contacts ------------------------------------------------
    companies, contacts, cid, ctid = [], [], 1, 1
    used = set()
    while len(companies) < 220:
        nm = f"{rng.choice(WORDS)} {rng.choice(WORDS)} {rng.choice(SUFFIX)}"
        if nm in used or nm.split()[0] == nm.split()[1]:
            continue
        used.add(nm)
        city = rng.choice(list(CITIES))
        emp = None if rng.random() < 0.08 else rng.choice([10, 25, 50, 120, 300, 800, 2000])
        companies.append((cid, nm, rng.choice(INDUSTRIES), city, CITIES[city], emp,
                          rand_date(rng, date(2024, 6, 1), END).isoformat()))
        for _ in range(rng.randint(1, 3)):
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            dom = nm.split()[0].lower() + nm.split()[1].lower() + ".example"
            phone = None if rng.random() < 0.12 else f"+91-9{rng.randint(100000000, 999999999)}"
            contacts.append((ctid, cid, f"{fn} {ln}",
                             rng.choice(["Founder", "Marketing Head", "CMO", "Brand Manager",
                                         "Operations Head", "Director", None]),
                             f"{fn.lower()}.{ln.lower()}@{dom}", phone))
            ctid += 1
        cid += 1
    con.executemany("INSERT INTO companies VALUES (?,?,?,?,?,?,?)", companies)
    con.executemany("INSERT INTO contacts VALUES (?,?,?,?,?,?)", contacts)
    region_of_company = {c[0]: c[4] for c in companies}
    contact_company = {c[0]: c[1] for c in contacts}

    # --- campaigns -----------------------------------------------------------
    campaigns = []
    for i in range(1, 11):
        s = rand_date(rng, START, date(2026, 8, 1))
        ch = rng.choice(["LinkedIn", "Instagram Ads", "Event", "Website"])
        campaigns.append((i, f"{ch} Push {s.strftime('%b %Y')}", ch, s.isoformat(),
                          (s + timedelta(days=rng.choice([30, 45, 60]))).isoformat(),
                          rng.choice([50_000, 100_000, 150_000, 250_000, 400_000])))
    con.executemany("INSERT INTO campaigns VALUES (?,?,?,?,?,?)", campaigns)

    # --- leads, deals, activities -------------------------------------------
    leads, deals, acts = [], [], []
    aid = 1
    for lid in range(1, 1201):
        contact = rng.randint(1, len(contacts))
        region = region_of_company[contact_company[contact]]
        rep = None if rng.random() < 0.05 else rng.choice(reps_by_region[region])
        source = rng.choices(SOURCES, weights=[25, 15, 20, 15, 10, 15])[0]
        camp = None
        if source in ("LinkedIn", "Instagram Ads", "Event", "Website") and rng.random() < 0.4:
            match = [c[0] for c in campaigns if c[2] == source]
            camp = rng.choice(match) if match else None
        service = rng.choice(SERVICES)
        created = rand_date(rng, START, END)
        age = (END - created).days

        p_win = SOURCE_WIN[source] * (rep_skill.get(rep, 0.6))
        closed_at = None
        if age > 45 and rng.random() < 0.85:          # older leads mostly closed
            won = rng.random() < min(p_win * 1.3, 0.9)
            status = "Won" if won else "Lost"
            closed = min(created + timedelta(days=rng.randint(10, 90)), END)
            closed_at = closed.isoformat()
            lo, hi = SERVICE_PRICE[service]
            amount = round(rng.randint(lo, hi), -3)
            deals.append((len(deals) + 1, lid, amount, status,
                          None if won else rng.choice(LOSS_REASONS), closed_at))
        else:
            status = rng.choices(STAGES, weights=[30, 25, 20, 15, 10])[0]

        leads.append((lid, contact, rep, camp, source, service, status,
                      created.isoformat(), closed_at))

        n_act = {"New": 0, "Contacted": 1, "Qualified": 2, "Proposal": 3,
                 "Negotiation": 4}.get(status, rng.randint(1, 6))
        last = date.fromisoformat(closed_at) if closed_at else END
        for _ in range(n_act):
            d = rand_date(rng, created, max(created, last))
            acts.append((aid, lid, rep, rng.choice(ACTIVITY_TYPES), d.isoformat(),
                         rng.choice([None, "Shared deck", "Follow-up pending",
                                     "Asked for revised quote", "Positive call"])))
            aid += 1

    con.executemany("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?)", leads)
    con.executemany("INSERT INTO deals VALUES (?,?,?,?,?,?)", deals)
    con.executemany("INSERT INTO activities VALUES (?,?,?,?,?,?)", acts)
    con.commit()
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="crm.db")
    args = ap.parse_args()
    import os
    if os.path.exists(args.out):
        os.remove(args.out)
    build(args.out)
    print(f"Wrote {args.out}")

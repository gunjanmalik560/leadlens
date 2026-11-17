"""LeadLens v2 - web app.  Run locally with:  streamlit run app.py"""
import json
import os
from pathlib import Path

import streamlit as st

# On Streamlit Cloud the key lives in st.secrets, not .env - copy it across
# before core.py reads the environment.
try:
    for k in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = st.secrets[k]
except Exception:
    pass  # no secrets file locally - .env is used instead

import core  # noqa: E402

HERE = Path(__file__).parent
MAX_QUESTIONS_PER_SESSION = 15   # protects the free-tier API quota

st.set_page_config(page_title="LeadLens", page_icon="🔎", layout="wide")


# ---------------------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=24 * 3600)
def cached_ask(question: str):
    """Same question -> reuse the answer instead of calling the API again."""
    return core.ask(question)


@st.cache_data
def eval_summary():
    files = sorted((HERE / "results").glob(f"{core.MODEL}.json"))
    if not files:
        return None
    res = json.loads(files[0].read_text(encoding="utf-8"))
    return sum(r["status"] == "correct" for r in res), len(res)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("About")
    st.write("LeadLens turns plain-English questions into SQL, runs them on a "
             "sales CRM database, and shows the answer with the query used.")
    summary = eval_summary()
    if summary:
        st.metric("Tested accuracy", f"{summary[0]}/{summary[1]}",
                  help="Execution accuracy on a 50-question test set "
                       "(15 easy, 20 medium, 15 hard).")
    st.caption(f"Model: {core.MODEL}")
    st.subheader("Safety")
    st.write("Read-only: only single SELECT queries run, on a read-only "
             "database connection. All data is synthetic.")
    with st.expander("Tables in the database"):
        st.markdown("""
- **leads**: source, service, status, rep, dates
- **deals**: closed leads: amount (INR), Won/Lost, loss reason
- **companies**: industry, city, region, size
- **contacts**: people at companies
- **sales_reps**: region, manager
- **campaigns**: channel, budget, dates
- **activities**: calls, emails, meetings, demos
""")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
st.title("🔎 LeadLens")
st.write("Ask a question about the sales pipeline in plain English.")

examples = [
    "Which lead source has the highest win rate?",
    "Show monthly won revenue for 2026",
    "Who is the top sales rep by won revenue in each region?",
    "What is the most common reason for losing a deal?",
]
st.caption("Try an example:")
cols = st.columns(len(examples))
for col, ex in zip(cols, examples):
    if col.button(ex, width="stretch"):
        st.session_state.question = ex

question = st.text_input("Your question", key="question",
                         placeholder="e.g. Which industry brings the most revenue?")

st.session_state.setdefault("asked", 0)

if question:
    if st.session_state.asked >= MAX_QUESTIONS_PER_SESSION:
        st.warning("Question limit reached for this session (free API tier). "
                   "Refresh the page later to ask more.")
        st.stop()
    with st.spinner("Writing SQL and running it..."):
        try:
            sql, df = cached_ask(question.strip())
            st.session_state.asked += 1
        except core.DailyQuotaExceeded:
            st.error("The free API quota for today is used up. Please try again tomorrow.")
            st.stop()
        except ValueError as e:
            st.error(f"Query blocked for safety: {e}")
            st.stop()
        except Exception as e:
            st.error("Sorry, that question couldn't be answered. Try rephrasing it.")
            with st.expander("Error details"):
                st.code(str(e))
            st.stop()

    st.subheader("Answer")
    df = df.round(2)  # display only: 63.2653 -> 63.27
    if df.empty:
        st.info("The query ran but returned no rows.")
    elif df.shape == (1, 1):
        value = df.iloc[0, 0]
        st.metric(df.columns[0], f"{value:,}" if isinstance(value, (int, float)) else value)
    else:
        # Automatic chart: first column = labels, second column = a number.
        if df.shape[1] >= 2 and 1 < len(df) <= 40 and df.dtypes.iloc[1].kind in "if":
            import altair as alt
            label, value = df.columns[0], df.columns[1]
            data = df[[label, value]].astype({label: str})
            tip = [alt.Tooltip(label), alt.Tooltip(value, format=",")]
            first = data[label].iloc[0]
            if len(first) == 7 and first[4] == "-":     # YYYY-MM -> line chart
                chart = alt.Chart(data).mark_line(point=True).encode(
                    x=alt.X(f"{label}:O", sort=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y(f"{value}:Q", axis=alt.Axis(format="~s")),
                    tooltip=tip)
            else:                                       # categories -> bars
                chart = alt.Chart(data).mark_bar().encode(
                    y=alt.Y(f"{label}:N", sort="-x", title=None),
                    x=alt.X(f"{value}:Q", axis=alt.Axis(format="~s")),
                    tooltip=tip)
            st.altair_chart(chart, width="stretch")
        # Table with thousands separators (5,668,000).
        numeric = [c for c in df.columns if df[c].dtype.kind in "if"]
        st.dataframe(df, width="stretch", hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="localized") for c in numeric})

    with st.expander("SQL used", expanded=False):
        st.code(sql, language="sql")
        st.download_button("Download results (CSV)", df.to_csv(index=False),
                           file_name="leadlens_results.csv", mime="text/csv")

"""Ask LeadLens a question from the terminal.

Usage: python ask.py "Which lead source has the highest win rate?"
"""
import os
import sys

from core import MODEL, ask

question = " ".join(sys.argv[1:]) or input("Your question: ")
print(f"Model: {MODEL} | API: {os.getenv('LLM_BASE_URL') or 'OpenAI default'}")
try:
    sql, df = ask(question)
    print("\nSQL:\n" + sql + "\n")
    print(df.to_string(index=False) if not df.empty else "(no rows)")
except Exception as e:
    print("Error:", e)
    resp = getattr(e, "response", None)
    if resp is not None:
        print("URL called:", resp.request.url)
        print("Details:", resp.text[:500] or "(empty)")
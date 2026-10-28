"""Step 8a: a small web UI over the pipeline you already built. Run from the project root:
    streamlit run app/streamlit_app.py
Four tabs, each calling existing code: process a document, reconcile a fund, the review queue, Ask.
Offline demo mode (no API key needed): extraction is replaced by the document's answer key, so the
page works for anyone, at no cost. Turn it off to call Claude for real."""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                      # so "import pipeline" works when Streamlit runs this file
os.chdir(ROOT)                                     # the pipeline's relative paths (data/...) start here

import pandas as pd                                # noqa: E402  (imports after the path fix on purpose)
import streamlit as st                             # noqa: E402
from dotenv import load_dotenv                     # noqa: E402

load_dotenv(ROOT / ".env")                         # your key from .env, so the app can call Claude

from eval.reconciliation import load_ledger        # noqa: E402
from pipeline.process import process_document     # noqa: E402
from pipeline.reconcile import reconcile          # noqa: E402
from pipeline.schemas import SCHEMAS               # noqa: E402
from pipeline.statement import parse_statement    # noqa: E402
from pipeline.validate import MasterData          # noqa: E402

GEN = ROOT / "data" / "generated"
KEY_FOLDERS = [GEN / "answer_keys", GEN / "hard_keys"]
SAMPLES = {                                        # named by file only: the app works out the type itself
    "CC-0001.pdf": "capital_calls/CC-0001.pdf", "DN-0001.pdf": "distributions/DN-0001.pdf",
    "OT-0002.pdf": "other/OT-0002.pdf", "HD-0001.pdf (hard set)": "hard/HD-0001.pdf",
    "HD-0002.pdf (hard set)": "hard/HD-0002.pdf", "HD-0004.pdf (hard set)": "hard/HD-0004.pdf",
    "HD-0014.pdf (hard set)": "hard/HD-0014.pdf"}

st.set_page_config(page_title="Inbox to Ledger", page_icon="📥", layout="wide")


@st.cache_resource
def master() -> MasterData:
    return MasterData.load()


@st.cache_resource
def ledger():
    return load_ledger()


def answer_key_extract(name: str):
    """Offline demo: return the answer key as if Claude had extracted it (no API call, no cost)."""
    def extract(text, doc_type):
        for folder in KEY_FOLDERS:
            key_file = folder / f"{Path(name).stem}.json"
            if key_file.exists():
                key = json.loads(key_file.read_text())
                fields = {f: key.get(f) for f in SCHEMAS[doc_type].model_fields if key.get(f) is not None}
                if "investor_name_shown" in key:
                    fields["investor_name"] = key["investor_name_shown"]
                try:
                    return SimpleNamespace(data=SCHEMAS[doc_type].model_validate(fields), error=None)
                except Exception as error:                     # e.g. the missing-due-date trap
                    return SimpleNamespace(data=None, error=f"invalid form: {error}")
        return SimpleNamespace(data=None, error="offline demo works only for the project's generated documents")
    return extract


st.title("📥 Inbox to Ledger")
st.caption("Fund documents in, verified and reconciled ledger data out. Synthetic data only.")
demo = st.sidebar.toggle("Offline demo (no API calls)", value=not os.getenv("ANTHROPIC_API_KEY"),
                         help="On: extraction comes from the answer key. Off: Claude reads the document.")
st.sidebar.markdown("**Pipeline:** read → classify (TF-IDF) → extract (Claude) → validate → match → reconcile")

tab_doc, tab_rec, tab_queue, tab_ask = st.tabs(["Process a document", "Reconciliation", "Review queue", "Ask"])

# ---------------------------------------------------------------- 1. one document
with tab_doc:
    left, right = st.columns([1, 2])
    with left:
        choice = st.selectbox("Sample PDF (the app detects its type)", list(SAMPLES))
        upload = st.file_uploader("…or upload a PDF", type="pdf")
        run = st.button("Process", type="primary")
    if run:
        if upload is not None:
            path = Path(tempfile.mkdtemp()) / upload.name
            path.write_bytes(upload.getvalue())
        else:
            path = GEN / SAMPLES[choice]
        with st.spinner("Reading, classifying, extracting, validating…"):
            record = process_document(path, master(), extract=answer_key_extract(path.name) if demo else None)
        with right:
            icon = {"accepted": "✅", "needs_review": "⚠️", "filed": "🗂️"}[record["status"]]
            st.subheader(f"{icon} {record['file']}: {record['status'].replace('_', ' ')}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Type", record.get("doc_type") or "unknown")
            c2.metric("Classifier confidence", f"{float(record['confidence']):.0%}" if "confidence" in record else "n/a")
            c3.metric("Investor", record.get("investor_id") or "n/a")
            if record.get("low_confidence"):
                st.info("The classifier was under 80% sure of the type (unfamiliar layout). Fields were still checked.")
            for error in record["errors"]:
                st.error(error)
            for warning in record["warnings"]:
                st.warning(warning)
            if "fields" in record:
                st.table(pd.DataFrame({"value": {k: str(v) for k, v in record["fields"].items()}}))
            with st.expander("Raw record (what the cloud saves in DynamoDB)"):
                st.json(record, expanded=False)

# ---------------------------------------------------------------- 2. reconciliation
with tab_rec:
    statements = sorted(p.stem for p in (GEN / "bank_statements").glob("BS-*.pdf")) + \
                 sorted(p.stem for p in (GEN / "hard_statements").glob("HS-*.pdf"))
    pick = st.selectbox("Bank statement (BS = normal, HS = hard)", statements)
    folder = "bank_statements" if pick.startswith("BS") else "hard_statements"
    statement = parse_statement(GEN / folder / f"{pick}.pdf")
    calls, dists = ledger()
    fund_id = master().accounts[statement.account_number]
    rec = reconcile(statement, calls[fund_id], dists[fund_id], master())

    paid = sum(i.status in ("paid", "paid_less_fee") for i in rec.calls)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fund", fund_id)
    c2.metric("Bank lines", len(statement.lines))
    c3.metric("Calls paid", f"{paid}/{len(rec.calls)}")
    c4.metric("Need review", len(rec.breaks))
    money = lambda x: f"{x:,.2f}" if x is not None else ""
    rows = [{"": "⚠️" if i.needs_review else "✅", "status": i.status, "document": i.doc_id or "",
             "expected": money(i.expected), "received": money(i.actual),
             "bank line": i.line.description if i.line else "", "note": i.note}
            for i in rec.calls + rec.distributions + rec.unmatched]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ---------------------------------------------------------------- 3. review queue
with tab_queue:
    from pipeline.daily import run as morning_run
    from pipeline.review import ReviewQueue

    if "queue_path" not in st.session_state:                  # a private queue per browser session
        st.session_state.queue_path = str(Path(tempfile.mkdtemp()) / "review.db")
    queue = ReviewQueue(st.session_state.queue_path)
    as_of = st.date_input("Morning of", date(2026, 7, 1), min_value=date(2026, 1, 1), max_value=date(2026, 12, 31))
    counts = morning_run(as_of, queue)
    st.caption(f"{counts['breaks']} breaks and {counts['due_soon']} calls due within 7 days. "
               f"Since the previous run: {counts['new']} new, {counts['closed']} closed automatically "
               "(change the date to watch items appear and close).")
    for item in queue.open_items():
        amount = f"${item.amount:,.2f}" if item.amount is not None else ""
        with st.expander(f"[{item.priority}] {item.kind.replace('_', ' ')} · {item.fund_id} · {item.doc_id or ''} · {amount}"):
            st.write(item.detail)
            note = st.text_input("Resolution note", key=f"note{item.id}")
            if st.button("Resolve", key=f"resolve{item.id}") and note.strip():
                queue.resolve(item.id, note, by="demo-user")
                st.rerun()

# ---------------------------------------------------------------- 4. ask
with tab_ask:
    question = st.text_input("Ask about the documents",
                             "In which city will Lakeshore Growth Fund IV hold its annual general meeting?")
    if demo:
        st.info("Ask needs Claude. Turn off offline demo in the sidebar (requires ANTHROPIC_API_KEY).")
    elif not os.getenv("ANTHROPIC_API_KEY"):
        st.error("No ANTHROPIC_API_KEY found. Add it to .env in the project folder and restart the app.")
    elif st.button("Ask", type="primary"):
        from pipeline.ask import answer, default_index
        index, corpus = default_index()
        with st.spinner("Retrieving 4 documents, asking Claude…"):
            result = answer(question, index, corpus)
        (st.success if result.found else st.warning)(result.text)
        st.caption(f"Cited: {', '.join(result.citations) or 'nothing'}  ·  retrieved: {', '.join(result.retrieved)}")
        for doc_id in result.citations:
            with st.expander(f"Source {doc_id}"):
                st.text(corpus[doc_id])
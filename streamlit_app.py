import streamlit as st
import os, subprocess, json
from datetime import datetime, timedelta, timezone
import glob
from src.config import OPENAI_API_KEY
from openai import OpenAI

# --- LOCAL DATE ---
LOCAL_OFFSET_HOURS = -4
local_today = (datetime.now(timezone.utc) + timedelta(hours=LOCAL_OFFSET_HOURS)).date()
today_str = local_today.isoformat()

# --- FILE PATHS ---
DAILY_DIR = "outputs/daily"
WEEKLY_DIR = "outputs/weekly"
os.makedirs(DAILY_DIR, exist_ok=True)
os.makedirs(WEEKLY_DIR, exist_ok=True)

st.set_page_config(page_title="Venezuela Watch", layout="wide")
st.title("🗞️ Venezuela Political & Economic Watch")
st.caption("Automated monitoring and scenario reasoning using GNews + GPT-4o")

tabs = st.tabs(["📅 Daily Report", "🗓️ Weekly Anlaysis", "💬 Interact"])

# -------------------------------------------------
# DAILY TAB
# -------------------------------------------------
with tabs[0]:
    st.subheader("Daily Report")

    # Check if today's report exists — if not, generate it
    today_file = f"{DAILY_DIR}/venezuela_{today_str}.md"
    if not os.path.exists(today_file):
        with st.spinner("Generating today's report..."):
            subprocess.run(["python", "-m", "src.daily_watch"], capture_output=True, text=True)

    # Refresh list of available reports
    files = sorted(glob.glob(f"{DAILY_DIR}/venezuela_*.md"))
    dates = [f.split("_")[-1].replace(".md", "") for f in files]

    # Handle case where still no reports exist
    if not dates:
        st.error("No daily reports available yet.")
    else:
        # Sort newest → oldest and show the most recent report by default
        sorted_dates = sorted(dates, reverse=True)
        selected_date = st.selectbox(
            "Select report date:",
            options=sorted_dates,
            index=0  # default to latest
        )

        # Load and display selected report
        selected_file = f"{DAILY_DIR}/venezuela_{selected_date}.md"
        with open(selected_file, "r", encoding="utf-8") as f:
            report = f.read()
        st.markdown(f"### 📰 Daily Report – {selected_date}")
        st.markdown(report)


# -------------------------------------------------
# WEEKLY TAB
# -------------------------------------------------
with tabs[1]:
    st.subheader("Weekly Anlaysis")

    # find newest file
    weekly_files = sorted(glob.glob(f"{WEEKLY_DIR}/venezuela_week_*.md"))
    if not weekly_files:
        st.info("No weekly report available yet.")
    else:
        latest_file = weekly_files[-1]
        latest_date = latest_file.split("_")[-1].replace(".md", "")
        st.markdown(f"### 📆 Weekly Report – {latest_date}")
        with open(latest_file, "r", encoding="utf-8") as f:
            st.markdown(f.read())

# -------------------------------------------------
# EXCHANGE TAB
# -------------------------------------------------
def load_recent_reasoning(log_path="data/logs/scenarios_log.jsonl", n_per_scenario=3):
    if not os.path.exists(log_path):
        return "No reasoning logs available yet."
    
    from collections import defaultdict
    scenario_notes = defaultdict(list)
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                scenario_notes[entry["id"]].append(entry)
            except:
                continue
    
    # keep only last n entries per scenario
    summary_texts = []
    for sid, entries in scenario_notes.items():
        entries = sorted(entries, key=lambda e: e["date"], reverse=True)[:n_per_scenario]
        for e in entries:
            summary_texts.append(
                f"**{e['title']} ({e['date']})** — {e['reasoning']} "
                f"(→ plausibility: {e['plausibility']}, confidence: {e['updated_confidence']})"
            )
    
    return "\n\n".join(summary_texts)

@st.cache_data(ttl=3600)
def load_brainstorm_context():
    ctx_parts = []

    # 1. Background context
    if os.path.exists("data/context/venezuela_context.md"):
        with open("data/context/venezuela_context.md", "r", encoding="utf-8") as f:
            ctx_parts.append(f.read())

    # 2. Scenarios (short summaries)
    if os.path.exists("data/context/venezuela_scenarios.json"):
        with open("data/context/venezuela_scenarios.json", "r", encoding="utf-8") as f:
            scenarios = json.load(f)
        text = "\n\n".join([f"**{s['title']}**: {s['narrative']}" for s in scenarios])
        ctx_parts.append("### Current Scenarios\n" + text)

    # 3. Latest weekly report
    weekly_files = sorted(glob.glob("outputs/weekly/venezuela_week_*.md"))
    if weekly_files:
        with open(weekly_files[-1], "r", encoding="utf-8") as f:
            ctx_parts.append("### Latest Weekly Report\n" + f.read())

    # 4. Recent reasoning logs
    log_summary = load_recent_reasoning()
    ctx_parts.append("### Recent Analytical Reasoning\n" + log_summary)

    return "\n\n---\n\n".join(ctx_parts)

with tabs[2]:
     # Create subtabs
    subtabs = st.tabs(["🧠 Brainstorm", "🧾 Review", "📊 Take Stock"])

    # 1️⃣ Brainstorm tab (chatbot)
    with subtabs[0]:
        st.subheader("💭 Brainstorm: Discuss Current Dynamics")

        # Initialize chat history
        if "messages" not in st.session_state:
            st.session_state.messages = [
                {"role": "assistant", "content": "Hi! Let’s discuss the current dynamics in Venezuela. What’s on your mind?"}
            ]

        # Display existing chat history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # User input
        if user_input := st.chat_input("Ask about Venezuela's current situation..."):
            # Display user message
            st.chat_message("user").markdown(user_input)
            st.session_state.messages.append({"role": "user", "content": user_input})

            # Generate model response
            with st.spinner("Thinking..."):
                context = load_brainstorm_context()

                # Build message context
                messages = [{"role": "system", "content": (
                    "You are an experienced political analyst specializing in Venezuela. "
                    "Maintain a thoughtful, grounded discussion. "
                    "Use the provided context and previous exchanges for continuity."
                )}]
                messages.extend(st.session_state.messages[-8:])  # include the recent conversation

                client = OpenAI(api_key=OPENAI_API_KEY)
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages + [
                        {"role": "user", "content": f"Context:\n{context}\n\nQuestion:\n{user_input}"}
                    ],
                    temperature=0.6,
                )
                reply = response.choices[0].message.content

            # Display assistant message
            with st.chat_message("assistant"):
                st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})

    # 2️⃣ Review tab (feedback loop placeholder)
    with subtabs[1]:
        st.subheader("🧾 Review: Assess Model Reasoning")
        st.info("This section will allow you to review the model’s scenario assessments and provide corrections.")

    # 3️⃣ Take Stock tab (scenario revision placeholder)
    with subtabs[2]:
        st.subheader("📊 Take Stock: Reassess Scenarios")
        st.info("This section will allow for periodic scenario restructuring and deeper analysis.")

    


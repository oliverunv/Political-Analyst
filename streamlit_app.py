import streamlit as st
import os, subprocess, json
from datetime import datetime, timedelta, timezone
import glob
from src.config import OPENAI_API_KEY
from openai import OpenAI

# --- LOCAL DATE (still useful for display if needed) ---
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

tabs = st.tabs(["📅 Daily Report", "📈 Weekly Analysis", "💬 Interact", "📝 Draft"])


# -------------------------------------------------
# DAILY TAB
# -------------------------------------------------
with tabs[0]:
    st.subheader("Daily Report")

    # ❌ Removed auto-generation via subprocess
    # ✅ Just load whatever is already in outputs/daily
    files = sorted(glob.glob(f"{DAILY_DIR}/venezuela_*.md"))
    dates = [os.path.basename(f).split("_")[-1].replace(".md", "") for f in files]

    if not dates:
        st.error("No daily reports available yet. Make sure your backend job has generated them in `outputs/daily`.")
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
    st.subheader("Weekly Analysis")

    weekly_files = sorted(glob.glob(f"{WEEKLY_DIR}/venezuela_week_*.md"))
    if not weekly_files:
        st.info("No weekly reports available yet. Make sure your backend job has generated them in `outputs/weekly`.")
    else:
        # Allow selecting among all weeks instead of only the latest
        week_labels = [
            os.path.basename(f).replace("venezuela_week_", "").replace(".md", "")
            for f in weekly_files
        ]
        # newest → oldest (string sort works fine for YYYY-MM-DD[_to_...] format)
        week_pairs = sorted(
            zip(week_labels, weekly_files),
            key=lambda x: x[0],
            reverse=True
        )

        default_label = week_pairs[0][0]
        selected_label = st.selectbox(
            "Select weekly report:",
            options=[w[0] for w in week_pairs],
            index=0  # latest by default
        )

        # Find the corresponding file
        selected_path = dict(week_pairs)[selected_label]
        st.markdown(f"### 📆 Weekly Report – {selected_label}")
        with open(selected_path, "r", encoding="utf-8") as f:
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
        # support both old "date" and new "report_generated_on" fields
        def get_sort_date(e):
            return e.get("date") or e.get("report_generated_on") or ""

        entries = sorted(entries, key=get_sort_date, reverse=True)[:n_per_scenario]
        for e in entries:
            display_date = e.get("date") or e.get("report_generated_on") or "n/a"
            summary_texts.append(
                f"**{e['title']} ({display_date})** — {e['reasoning']} "
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
    st.subheader("💭 Brainstorm: Discuss Current Dynamics")

    # 1️⃣ Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi! Let’s discuss the current dynamics in Venezuela. What’s on your mind?"
            }
        ]

    # 2️⃣ Display existing chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 3️⃣ Chat input (this will be pinned to the bottom)
    user_input = st.chat_input("Ask about Venezuela's current situation...")

    # 4️⃣ Handle new input
    if user_input:
        # Store user message in state
        st.session_state.messages.append({"role": "user", "content": user_input})

        # Generate model reply and store it in state
        with st.spinner("Thinking..."):
            context = load_brainstorm_context()

            messages_for_model = [
                {
                    "role": "system",
                    "content": (
                        "You are an experienced political analyst specializing in Venezuela. "
                        "Maintain a thoughtful, grounded discussion. "
                        "Use the provided context and previous exchanges for continuity."
                    ),
                }
            ]
            # include recent conversation
            messages_for_model.extend(st.session_state.messages[-8:])

            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages_for_model + [
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion:\n{user_input}",
                    }
                ],
                temperature=0.6,
            )
            reply = response.choices[0].message.content

        st.session_state.messages.append({"role": "assistant", "content": reply})

        # 5️⃣ Rerun so the new messages show up in the history *above* the input
        st.rerun()

# -------------------------------------------------
# DRAFT NOTES TAB
# -------------------------------------------------
with tabs[3]:
    st.subheader("📝 Draft Background Notes & Talking Points")

    st.markdown(
        "Use this tab to generate and iteratively refine background notes or talking points, "
        "grounded in the latest context and reporting."
    )

    # Initialise state for the drafting workflow
    if "draft_text" not in st.session_state:
        st.session_state.draft_text = ""
    if "draft_meta" not in st.session_state:
        st.session_state.draft_meta = {}

    doc_type = st.radio(
        "What do you need?",
        options=["Background note", "Talking points"],
        horizontal=True,
    )

    topic = st.text_input(
        "Meeting information",
        placeholder="e.g. SG Meeting with the PR of Venezuela on current developments",
        value=st.session_state.draft_meta.get("topic", "")
    )

    initial_instructions = st.text_area(
        "Initial instructions (optional)",
        placeholder="E.g. focus on political risks, keep under 1 page, highlight implications for regional security...",
        value=st.session_state.draft_meta.get("initial_instructions", "")
    )

    include_context = st.checkbox(
        "Include latest context, scenarios, and weekly report",
        value=True
    )

    col_gen, col_clear = st.columns([3, 1])
    generate_btn = col_gen.button("Generate draft")
    clear_btn = col_clear.button("Clear draft")

    if clear_btn:
        st.session_state.draft_text = ""
        st.session_state.draft_meta = {}
        st.success("Draft cleared.")

    # --- Helper to call OpenAI once for drafting/refining ---
    def call_drafting_model(instruction_block: str, draft: str | None = None):
        context_text = load_brainstorm_context() if include_context else ""

        examples = """
EXAMPLE 1: Background note
Title: Democratic Republic of the Congo - Recent Developments

The Democratic Republic of the Congo is undergoing a period of political consolidation following the re-election of President Félix Tshisekedi in December 2023 and the formation of a new government led by Prime Minister Judith Suminwa in June 2024. The government’s programme of action for 2024–2028 prioritizes national security, allocating nearly 19 per cent of its $92.9 billion budget to strengthening defense and security forces and reintegration of demobilized youth. Despite these efforts, tensions with Rwanda remain high, with both sides accusing each other of violating the 30 July ceasefire agreement under the Luanda process. While mediation efforts led by Angola have resulted in the launch of a Reinforced Ad Hoc Verification Mechanism, progress toward a comprehensive peace agreement has been slow, and the DRC continues to reject direct negotiations with the M23, which it designates as a terrorist group.
The security situation in eastern DRC remains volatile, marked by persistent clashes between the M23 and armed groups aligned with the FARDC in North Kivu, as well as ongoing operations against the Allied Democratic Forces (ADF) in Ituri. The Group of Experts has documented foreign military involvement, notably Rwanda’s support to M23 and the deployment of RDF troops, alongside reports of FARDC collaboration with FDLR and Wazalendo groups. Armed groups continue to exploit natural resources, including coltan and gold, fueling conflict dynamics. Human rights violations, including indiscriminate attacks on civilians, recruitment of children, and conflict-related sexual violence, have intensified, contributing to a humanitarian crisis affecting over 6.9 million displaced persons. Despite MONUSCO’s withdrawal from South Kivu and the deployment of SAMIDRC with an offensive mandate, protection challenges persist, underscoring the fragility of security and governance in the eastern provinces.

EXAMPLE 2: Talking points 
Heading: Proposed talking points for SG Meeting with the PR of the DRC on current developments
- Express appreciation for the Government’s efforts to address insecurity in the eastern provinces and reiterate the United Nations’ full support for initiatives aimed at restoring peace and stability. 
- Welcome the Government’s continued engagement in the Luanda process and emphasize the importance of implementing the 30 July ceasefire agreement and the harmonized plan for neutralizing armed groups. 
- Express concern over reports of indiscriminate attacks and violations of international humanitarian and human rights law, including recruitment and use of children. 

"""

        style_label = "background note" if doc_type == "Background note" else "talking points"

        system_msg = (
            "You are a UN political affairs officer drafting internal background notes and talking points. "
            "Match the structure and tone of the examples provided, but do not copy their wording or facts. "
            "For background notes, use a title and numbered sections with short factual paragraphs. "
            "For talking points, use a clear heading and concise bullets, grouped under subheadings if needed. "
            "Maintain a neutral, diplomatic tone and base all content only on the provided context and instructions. "
        )

        if draft:
            # Refinement mode
            user_prompt = f"""
You are refining an existing {style_label}.

Current draft:
\"\"\"markdown
{draft}
\"\"\"

User instructions for revision:
{instruction_block}

Meeting information:
{topic}

Context to ground your revision (if provided):
{context_text}

Rewrite the draft in full, applying the instructions while preserving structure and factual grounding.
"""
        else:
            # Initial generation
            user_prompt = f"""
Please draft a {style_label}.

Meeting information:
{topic}

Initial instructions:
{instruction_block or "none"}

Use the following examples for structure and tone (do not copy wording):
{examples}

Context to ground your draft (if provided):
{context_text}
"""

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content

    # --- Generate initial draft ---
    if generate_btn:
        if not topic.strip():
            st.error("Please provide at least a topic or meeting description.")
        else:
            with st.spinner("Drafting..."):
                draft = call_drafting_model(initial_instructions, draft=None)
                st.session_state.draft_text = draft
                st.session_state.draft_meta = {
                    "doc_type": doc_type,
                    "topic": topic,
                    "initial_instructions": initial_instructions,
                }

    # --- Show current draft + refinement controls ---
    if st.session_state.draft_text:
        st.markdown("### ✍️ Current draft")
        st.markdown(st.session_state.draft_text)

        st.markdown("---")
        st.markdown("#### 🔧 Refine this draft")

        refinement_instr = st.text_area(
            "Refinement instructions",
            placeholder="E.g. shorten the background, add one bullet on regional reactions, highlight risks for the political process.",
            key="refinement_instr",
        )

        if st.button("Apply refinement"):
            if not refinement_instr.strip():
                st.warning("Please add some refinement instructions.")
            else:
                with st.spinner("Refining draft..."):
                    new_draft = call_drafting_model(refinement_instr, draft=st.session_state.draft_text)
                    st.session_state.draft_text = new_draft
                    st.success("Draft updated.")
                    st.rerun()
import os, json, time, requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from .config import GNEWS_API_KEY, OPENAI_API_KEY, QUERY, LANGS


def parse_week_start_from_filename(filename):
    prefix = "venezuela_week_"
    suffix = ".md"
    if not (filename.startswith(prefix) and filename.endswith(suffix)):
        raise ValueError("Invalid filename")
    date_part = filename[len(prefix):-len(suffix)]
    monday_str = date_part.split("_to_")[0]
    return datetime.strptime(monday_str, "%Y-%m-%d").date()


def find_latest_report_start(dir_path="outputs/weekly"):
    if not os.path.isdir(dir_path):
        return None
    latest = None
    for name in os.listdir(dir_path):
        try:
            start = parse_week_start_from_filename(name)
        except ValueError:
            continue
        if latest is None or start > latest:
            latest = start
    return latest

# -----------------------------------------------------
# 🕒 LOCAL DATE
# -----------------------------------------------------
LOCAL_OFFSET_HOURS = -4  # Example: UTC-4 (New York)
local_today = (datetime.now(timezone.utc) + timedelta(hours=LOCAL_OFFSET_HOURS)).date()

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------
# 1️⃣ FETCH WEEKLY NEWS (for an arbitrary week)
# -----------------------------------------------------
def fetch_week_for_range(start_date, end_date):
    """
    Fetch news articles for a specific inclusive date range [start_date, end_date].
    Example: 2025-11-10 to 2025-11-16 (7 days).
    """
    print(f"\n⏳ Fetching weekly news {start_date} → {end_date} (via GNews)...")
    base = "https://gnews.io/api/v4/search"

    # cache filename per week-range
    label = f"{start_date}_to_{end_date}"
    path = f"data/raw/news_week_{label}.json"

    # ✅ Reuse cached file if available
    if os.path.exists(path):
        print(f"📦 Using cached file: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    results = []
    day = start_date
    while day <= end_date:
        print(f"📅 Fetching {day}...")
        for lang in LANGS:
            params = {
                "apikey": GNEWS_API_KEY,
                "q": QUERY,
                "lang": lang,
                "from": f"{day}T00:00:00Z",
                "to": f"{day}T23:59:59Z",
                "max": 10,  # Free-tier limit
            }
            r = requests.get(base, params=params, timeout=30)
            if r.status_code != 200:
                print(f"⚠️ Error {r.status_code}: {r.text}")
                continue
            articles = r.json().get("articles", [])
            for a in articles:
                a["lang"] = lang
            results.extend(articles)
            time.sleep(1.2)
        day += timedelta(days=1)

    os.makedirs("data/raw", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {len(results)} articles → {path}")
    return results

# -----------------------------------------------------
# 2️⃣ CLEAN & RANK ARTICLES
# -----------------------------------------------------
KEYWORDS = ["venezuela", "caracas", "maduro", "pdvsa", "chevron",
            "opposition", "sanction", "machado"]

def clean_rank(raw):
    """Filter and rank relevant articles based on keywords."""
    curated = []
    for r in raw:
        text = " ".join([r.get("title", ""), r.get("description", ""), r.get("content", "")]).lower()
        if "venezuela" not in text:
            continue
        if not any(k in text for k in KEYWORDS):
            continue
        if len(r.get("description", "")) < 40:
            continue
        r["_score"] = sum(text.count(k) for k in KEYWORDS)
        curated.append(r)

    curated.sort(key=lambda x: x["_score"], reverse=True)
    os.makedirs("data/curated", exist_ok=True)
    path = "data/curated/venezuela_weekly.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(curated, f, ensure_ascii=False, indent=2)
    print(f"✅ Curated {len(curated)} relevant articles → {path}")
    return curated


# -----------------------------------------------------
# 3️⃣ LOAD CONTEXT & SCENARIOS
# -----------------------------------------------------
def load_scenarios():
    path = "data/context/venezuela_scenarios.json"
    if not os.path.exists(path):
        raise FileNotFoundError("❌ Missing scenario file: data/context/venezuela_scenarios.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_context():
    path = "data/context/venezuela_context.md"
    if not os.path.exists(path):
        print("⚠️ No context file found → continuing without it.")
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


# -----------------------------------------------------
# 4️⃣ BUILD TEXT CONTEXT
# -----------------------------------------------------
def build_context(items, cap_chars=10000):
    """Assemble a condensed text block from curated articles."""
    chunks, used = [], 0
    for it in items:
        title, url = it.get("title", ""), it.get("url") or ""
        desc, content = it.get("description") or "", it.get("content") or ""
        piece = f"- {title} [{url}]\n{desc}\n{content}\n"
        if used + len(piece) > cap_chars:
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks)


# -----------------------------------------------------
# 5️⃣ SUMMARIZE WEEKLY DEVELOPMENTS
# -----------------------------------------------------
def summarize_week(curated, scenarios, context):
    """Generate structured reasoning (internal) and narrative summary (public)."""
    ctx = build_context(curated)

    scenario_text = "\n".join([
        f"### {s['id']} – {s['title']}\n{s['narrative']}\n"
        for s in scenarios
    ])

    # ---- Structured reasoning (internal use) ----
    reasoning_prompt = f"""
You are a geopolitical analyst assessing developments in Venezuela.

Your task:
Evaluate how the plausibility of each scenario changed this week, based on factual developments.

Return ONLY a valid JSON array (no markdown or explanations).
Each element must have the following fields and structure — populate each field based on your own assessment, not the example values:

[
  {{
    "id": "SCENARIO_ID",
    "title": "SCENARIO_TITLE",
    "plausibility": "up" | "down" | "steady",
    "reasoning": "2–3 factual sentences explaining why plausibility changed, referencing evidence from this week.",
    "updated_confidence": FLOAT between 0 and 1
  }}
]

---
Context:
{context}

---
Scenarios:
{scenario_text}

---
Weekly News Feed:
{ctx}
"""
    print("🤖 Calling OpenAI for structured reasoning...")
    reasoning_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "Output only a valid JSON array following the structure above. Populate all fields based on reasoning; do not repeat example values or explanations."
            },
            {"role": "user", "content": reasoning_prompt},
        ],
        temperature=0.3,
    )

    def strip_code_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        return text

    raw_output = reasoning_resp.choices[0].message.content or ""
    raw_output = strip_code_fences(raw_output)
    structured_reasoning = json.loads(raw_output)

    # ---- Narrative summary (public output) ----
    narrative_prompt = f"""
You are writing the public Weekly Watch Report for Venezuela.

Using the following internal analysis:
{structured_reasoning}

Write a cohesive report:
- Factual Summary: 1–2 paragraphs summarizing verified factual developments from the past 7 days.
Avoid speculation or editorial tone.
- Scenario Assessment: analytical section (Scenario Assessment) using the provided context and scenarios and describing shifts in plausibility for each scenario. Do not indicate quantitative scores but only provide a qualitative assessment. 
- Forward Outlook: 3–5 bullet points for key trends or uncertainties to watch next week. Avoid speculation of what is likely to happen but identify key issues that are important to observe.
"""
    print("📝 Generating narrative report...")
    narrative_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You write factual, polished geopolitical summaries."},
            {"role": "user", "content": narrative_prompt}
        ],
        temperature=0.5,
    )

    return structured_reasoning, narrative_resp.choices[0].message.content


# -----------------------------------------------------
# 6️⃣ MAIN PIPELINE – run for last completed week
# -----------------------------------------------------
def generate_weekly_report(week_start, week_end, local_today, context, scenarios):
    label = f"{week_start}_to_{week_end}"
    print(f"🗓️ Generating Weekly Watch for {week_start} → {week_end} (label: {label})")

    articles = fetch_week_for_range(week_start, week_end)
    if not articles:
        print(f"⚠️ No articles for week {label}, aborting.")
        raise SystemExit(0)

    curated = clean_rank(articles)
    if not curated:
        print(f"⚠️ No curated Venezuela articles for week {label}, aborting.")
        raise SystemExit(0)

    print("🧠 Generating weekly synthesis...")
    structured_reasoning, summary = summarize_week(curated, scenarios, context)

    os.makedirs("outputs/weekly", exist_ok=True)
    out_path = f"outputs/weekly/venezuela_week_{label}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"\n✅ Weekly Watch saved → {out_path}")

    os.makedirs("data/logs", exist_ok=True)
    log_path = "data/logs/scenarios_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        for e in structured_reasoning:
            e["week_start"] = str(week_start)
            e["week_end"] = str(week_end)
            e["report_generated_on"] = str(local_today)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"🗂️ Logged structured reasoning → {log_path}")

    print("\n--- Preview ---\n")
    print(summary[:800])
    print("\n--- Scenario Reasoning ---")
    for e in structured_reasoning:
        print(f"{e['id']} ({e['plausibility']}): {e['reasoning']}")


if __name__ == "__main__":
    local_today = (datetime.now(timezone.utc) + timedelta(hours=LOCAL_OFFSET_HOURS)).date()
    print(f"📆 Local today: {local_today}")

    weekday = local_today.weekday()
    current_week_monday = local_today - timedelta(days=weekday)

    target_week_start = current_week_monday - timedelta(days=7)

    latest_existing_start = find_latest_report_start()
    weeks_to_generate = []

    if latest_existing_start is None:
        weeks_to_generate.append(target_week_start)
    else:
        candidate = latest_existing_start + timedelta(days=7)
        while candidate <= target_week_start:
            weeks_to_generate.append(candidate)
            candidate += timedelta(days=7)

    if not weeks_to_generate:
        print("✅ Weekly reports are up to date. Nothing to generate.")
        raise SystemExit(0)

    context = load_context()
    scenarios = load_scenarios()

    for start in weeks_to_generate:
        end = start + timedelta(days=6)
        generate_weekly_report(start, end, local_today, context, scenarios)

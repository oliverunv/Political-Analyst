import os, json, time, requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from .config import GNEWS_API_KEY, OPENAI_API_KEY, QUERY, LANGS

# -----------------------------------------------------
# 🕒 LOCAL DATE
# -----------------------------------------------------
LOCAL_OFFSET_HOURS = -4  # Example: UTC-4 (New York)
local_today = (datetime.now(timezone.utc) + timedelta(hours=LOCAL_OFFSET_HOURS)).date()

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------
# 1️⃣ FETCH WEEKLY NEWS (with caching)
# -----------------------------------------------------
def fetch_week():
    """Fetch or reuse this week's news articles from GNews."""
    print("⏳ Fetching this week's news (via GNews)...")
    base = "https://gnews.io/api/v4/search"
    today = local_today
    path = f"data/raw/news_week_{today}.json"

    # ✅ Reuse cached file if available
    if os.path.exists(path):
        print(f"📦 Using cached file: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    results = []
    for i in range(7):
        day = today - timedelta(days=i)
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
# 6️⃣ MAIN PIPELINE
# -----------------------------------------------------
if __name__ == "__main__":
    articles = fetch_week()
    curated = clean_rank(articles)
    context = load_context()
    scenarios = load_scenarios()

    print("🧠 Generating weekly synthesis...")
    structured_reasoning, summary = summarize_week(curated, scenarios, context)

    # Save narrative report
    os.makedirs("outputs/weekly", exist_ok=True)
    out_path = f"outputs/weekly/venezuela_week_{local_today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"\n✅ Weekly Watch saved → {out_path}")

    # Save structured reasoning
    os.makedirs("data/logs", exist_ok=True)
    log_path = "data/logs/scenarios_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        for e in structured_reasoning:
            e["date"] = str(local_today)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"🗂️ Logged structured reasoning → {log_path}")

    # Console preview
    print("\n--- Preview ---\n")
    print(summary[:800])
    print("\n--- Scenario Reasoning ---")
    for e in structured_reasoning:
        print(f"{e['id']} ({e['plausibility']}): {e['reasoning']}")

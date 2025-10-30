import os, json, datetime, time, requests
from openai import OpenAI
from src.config import GNEWS_API_KEY, OPENAI_API_KEY, QUERY, LANGS, TODAY
from datetime import datetime, timedelta, timezone

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------
# 1️⃣ FETCH: get today's articles (GNews)
# -----------------------------------------------------
def fetch_articles():
    print("⏳ Fetching today's news (via GNews)...")
    BASE = "https://gnews.io/api/v4/search"
    results = []

    # --- Time window ---
    LOCAL_OFFSET_HOURS = -4
    now = datetime.now(timezone.utc) + timedelta(hours=LOCAL_OFFSET_HOURS)
    end_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
    # if run before 8 a.m., still close previous window
    if now.hour < 8:
        end_time -= timedelta(days=1)
    start_time = end_time - timedelta(days=1)

    from_date = start_time.isoformat().replace("+00:00", "Z")
    to_date = end_time.isoformat().replace("+00:00", "Z")
    report_date = end_time.date().isoformat()

    print(f"🕒 Time window: {from_date} → {to_date}")

    for lang in LANGS:
        params = {
            "apikey": GNEWS_API_KEY,
            "q": QUERY,
            "lang": lang,
            "from": from_date,
            "to": to_date,
            "max": 10,  # Free-tier limit
        }

        r = requests.get(BASE, params=params, timeout=30)
        if r.status_code >= 400:
            print(f"⚠️ Error {r.status_code}: {r.text}")
            continue

        payload = r.json()
        articles = payload.get("articles", [])
        for a in articles:
            a["lang"] = lang
        results.extend(articles)

        time.sleep(1.2)  # respect rate limit

    os.makedirs("data/raw", exist_ok=True)
    raw_path = f"data/raw/news_{TODAY}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ Fetched {len(results)} articles → {raw_path}")
    return results, report_date


# -----------------------------------------------------
# 2️⃣ CLEAN & RANK: filter and prioritize relevant items
# -----------------------------------------------------
KEYWORDS = ["venezuela", "caracas", "maduro", "pdvsa", "chevron", "opposition", "sanction"]

def clean_rank(raw):
    curated = []
    for r in raw:
        title = r.get("title") or ""
        desc = r.get("description") or ""
        content = r.get("content") or ""
        text = (title + " " + desc + " " + content).lower()

        if "venezuela" not in text:
            continue
        if not any(k in text for k in KEYWORDS):
            continue
        if len(desc) < 40:
            continue

        r["_score"] = sum(text.count(k) for k in KEYWORDS)
        curated.append(r)

    curated.sort(key=lambda x: x["_score"], reverse=True)
    os.makedirs("data/curated", exist_ok=True)
    path = f"data/curated/venezuela_latest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(curated, f, ensure_ascii=False, indent=2)
    print(f"✅ Curated {len(curated)} relevant articles → {path}")
    return curated


# -----------------------------------------------------
# 3️⃣ SUMMARIZE: generate the daily brief
# -----------------------------------------------------
def build_context(items, cap_chars=6000):
    chunks, used = [], 0
    for it in items:
        title = it.get("title","")
        src   = it.get("url") or ""
        desc  = it.get("description") or ""
        content = it.get("content") or ""
        piece = f"- {title} [{src}]\n{desc}\n{content}\n"
        if used + len(piece) > cap_chars:
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks)

def summarize(curated):
    ctx = build_context(curated)
    prompt = f"""
Summarize only verified factual developments about Venezuela from the following articles.
Avoid speculation, background, or analysis.
Write a concise 180–220 word daily update.
Then list 3-5 bullet points under **Key Developments Today**.

Articles:
{ctx}
"""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role":"system","content":"You summarize daily news factually and concisely."},
            {"role":"user","content":prompt}
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content


# -----------------------------------------------------
# 4️⃣ MAIN PIPELINE
# -----------------------------------------------------
if __name__ == "__main__":
    articles, report_date = fetch_articles()
    curated = clean_rank(articles)
    summary = summarize(curated)

    os.makedirs("outputs/daily", exist_ok=True)
    out_path = f"outputs/daily/venezuela_{report_date}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)

    print(f"\n✅ Daily summary saved → {out_path}")
    print("\n--- Preview ---\n")
    print(summary[:800])
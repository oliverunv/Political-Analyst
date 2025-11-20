import os, json, time, requests
from openai import OpenAI
from src.config import GNEWS_API_KEY, OPENAI_API_KEY, QUERY, LANGS
from datetime import datetime, timedelta, timezone

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------
# 🌍 LOCAL TIME SETTINGS
# -----------------------------------------------------
# New York: -5 in winter (EST), -4 in summer (EDT)
LOCAL_OFFSET_HOURS = -5  # adjust seasonally if needed
LOCAL_TZ = timezone(timedelta(hours=LOCAL_OFFSET_HOURS))

# -----------------------------------------------------
# 1️⃣ FETCH: get articles for the last completed 24h window
#     Window ends at 08:00 local on report_date
# -----------------------------------------------------
def fetch_articles():
    print("⏳ Fetching daily news (via GNews)...")
    BASE = "https://gnews.io/api/v4/search"
    results = []

    # --- Determine report_date based on local time ---
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(LOCAL_TZ)
    local_today = now_local.date()

    # If before 08:00 → close previous day's window
    # If after 08:00 → close today's window
    if now_local.hour < 8:
        report_date = local_today - timedelta(days=1)
    else:
        report_date = local_today

    # End of window: 08:00 local on report_date
    end_local = datetime(
        year=report_date.year,
        month=report_date.month,
        day=report_date.day,
        hour=8,
        minute=0,
        second=0,
        tzinfo=LOCAL_TZ,
    )
    start_local = end_local - timedelta(days=1)

    # Convert to UTC for API
    start_time = start_local.astimezone(timezone.utc)
    end_time = end_local.astimezone(timezone.utc)

    from_date = start_time.isoformat().replace("+00:00", "Z")
    to_date = end_time.isoformat().replace("+00:00", "Z")

    print(f"📆 Local now: {now_local} (today={local_today})")
    print(f"🗓️ Report date: {report_date}")
    print(f"🕒 Time window (UTC): {from_date} → {to_date}")

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
    raw_path = f"data/raw/news_{report_date}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"🔎 Total articles fetched: {len(results)}")
    print(f"✅ Fetched articles saved → {raw_path}")

    # Return both list and ISO string for filenames
    return results, report_date.isoformat()


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
    path = "data/curated/venezuela_latest.json"
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

    if not articles:
        print(f"⚠️ No articles found for {report_date}, aborting.")
        raise SystemExit(0)

    curated = clean_rank(articles)
    if not curated:
        print(f"⚠️ No curated Venezuela articles for {report_date}, aborting.")
        raise SystemExit(0)

    summary = summarize(curated)

    os.makedirs("outputs/daily", exist_ok=True)
    out_path = f"outputs/daily/venezuela_{report_date}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)

    print(f"\n✅ Daily summary saved → {out_path}")
    print("\n--- Preview ---\n")
    print(summary[:800])

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
# Helper: calculate which date should be reported today
# -----------------------------------------------------
def determine_report_date(now=None):
    """Return the date whose 24h window just closed.

    The pipeline should *always* generate the report for the previous
    local day, regardless of the current local time. This keeps behavior
    consistent even when running after the daily cutoff.
    """

    now_utc = now or datetime.now(timezone.utc)
    now_local = now_utc.astimezone(LOCAL_TZ)
    return now_local.date() - timedelta(days=1)


def time_window_for_date(report_date):
    """Return the 24h local window for the given date.

    The window spans the full calendar day in the configured local
    timezone: from 00:00 at the start of ``report_date`` through
    00:00 of the following day.
    """

    start_local = datetime(
        year=report_date.year,
        month=report_date.month,
        day=report_date.day,
        hour=0,
        minute=0,
        second=0,
        tzinfo=LOCAL_TZ,
    )
    end_local = start_local + timedelta(days=1)
    return start_local, end_local


# -----------------------------------------------------
# 1️⃣ FETCH: get articles for the last completed 24h window
# -----------------------------------------------------
def fetch_articles(report_date=None):
    print("⏳ Fetching daily news (via GNews)...")
    BASE = "https://gnews.io/api/v4/search"
    results = []

    # Determine which date to generate a report for (default: today's window)
    report_date = report_date or determine_report_date()

    # Use the full 24h local calendar day window
    start_local, end_local = time_window_for_date(report_date)

    # Convert to UTC for API
    start_time = start_local.astimezone(timezone.utc)
    end_time = end_local.astimezone(timezone.utc)

    from_date = start_time.isoformat().replace("+00:00", "Z")
    to_date = end_time.isoformat().replace("+00:00", "Z")

    # Log for visibility when backfilling multiple days
    now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    print(f"📆 Local now: {now_local}")
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
# Helper: find the most recent already-generated report
# -----------------------------------------------------
def latest_report_date(daily_dir="outputs/daily"):
    """Return the latest report date found in the outputs directory."""

    if not os.path.isdir(daily_dir):
        return None

    latest = None
    for fname in os.listdir(daily_dir):
        if not fname.startswith("venezuela_") or not fname.endswith(".md"):
            continue

        date_part = fname[len("venezuela_") : -3]
        try:
            current = datetime.fromisoformat(date_part).date()
        except ValueError:
            continue

        if (latest is None) or (current > latest):
            latest = current

    return latest


# -----------------------------------------------------
# 4️⃣ MAIN PIPELINE
# -----------------------------------------------------
if __name__ == "__main__":
    os.makedirs("outputs/daily", exist_ok=True)

    # 1) Identify the most recent saved report (if any)
    last_saved = latest_report_date()

    # 2) Determine which report date we are expected to generate today
    expected_report = determine_report_date()

    # 3) If there is a gap, backfill each missing date in order
    if last_saved is None:
        next_date = expected_report
    else:
        next_date = last_saved + timedelta(days=1)

    # 4) Iterate from the first missing date through the expected date
    current = next_date
    while current <= expected_report:
        print(f"\n🚀 Generating report for {current}...")
        articles, report_date = fetch_articles(report_date=current)

        if not articles:
            print(f"⚠️ No articles found for {report_date}, aborting.")
            raise SystemExit(0)

        curated = clean_rank(articles)
        if not curated:
            print(f"⚠️ No curated Venezuela articles for {report_date}, aborting.")
            raise SystemExit(0)

        summary = summarize(curated)

        out_path = f"outputs/daily/venezuela_{report_date}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(summary)

        print(f"\n✅ Daily summary saved → {out_path}")
        print("\n--- Preview ---\n")
        print(summary[:800])

        current += timedelta(days=1)

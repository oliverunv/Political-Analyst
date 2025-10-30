import os, datetime
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timedelta, timezone

LOCAL_TZ_OFFSET = -4  # adjust to your actual offset if needed
local_today = (datetime.now(timezone.utc) + timedelta(hours=LOCAL_TZ_OFFSET)).date()

TODAY = local_today.isoformat()

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")

# Query knobs (tweak freely)
QUERY = '(Venezuela OR Caracas OR PDVSA OR "Nicolás Maduro" OR "Machado")'
LANGS = ['en','es']          # bilingual to start
SINCE_DAYS = 1               # last N days per run
PAGE_SIZE = 50               # cap per page to respect free tier
MAX_PAGES = 2                # keep costs predictable

TODAY = local_today.isoformat()

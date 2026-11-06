import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, odds_api as O, todays_best as TB
from datetime import datetime
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
key = os.environ.get("ODDS_API_KEY")
_, hdr = O._get("sports", {"apiKey": key})
print("QUOTA", hdr)
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", d, BBD.O.DEFAULT_BOOK)
_, hdr2 = O._get("sports", {"apiKey": key})
print("QUOTA after one NBA board", hdr2)
TB.save_props("NBA", d, plays, meta)
print("SAVED", (TB.load_props("NBA", d) or {}).get("at"), len((TB.load_props("NBA", d) or {}).get("rows") or []))

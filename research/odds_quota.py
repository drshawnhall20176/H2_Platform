import os, requests
r = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": os.environ["ODDS_API_KEY"]}, timeout=20)
print("status", r.status_code, "body", r.text[:300])
print("headers", {k: v for k, v in r.headers.items() if "requests" in k.lower()})

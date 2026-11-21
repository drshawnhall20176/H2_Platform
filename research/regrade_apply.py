import os
os.environ["REGRADE_APPLY"] = "1"
exec(open("research/regrade_settled.py").read())

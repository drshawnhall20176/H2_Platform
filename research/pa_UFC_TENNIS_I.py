import os
os.environ["AUDIT_SPORTS"] = "UFC,TENNIS,INTL,SOCCER,GENERAL"
exec(open("research/page_audit.py").read())

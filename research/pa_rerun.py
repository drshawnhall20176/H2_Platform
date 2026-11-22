import os
os.environ["AUDIT_SPORTS"] = "NFL,NBA,NHL,NCAAF,NCAAMB"
os.environ["AUDIT_PAGES"] = "0_#,2_Graded,3_Sugg,4_Spec,16_#,17_Model,18_#,19_Track"
exec(open("research/page_audit.py").read())

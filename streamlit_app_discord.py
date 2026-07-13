"""
Second entrypoint — exists ONLY because Streamlit Community Cloud requires each deployed app to
point at its own main file; two apps can't share one entrypoint in the same repo (confirmed by
Streamlit staff: https://discuss.streamlit.io/t/deploying-different-apps-from-same-github-script).

There is no logic here and there never should be — all of it lives in streamlit_app.py's run().
This file is the "Main file path" for the Discord/public Streamlit Cloud deployment ONLY. The
owner deployment keeps using streamlit_app.py directly, unchanged.

The two deployments behave differently through exactly one thing: the AUDIENCE secret set in
each app's own Settings -> Secrets on Streamlit Cloud (owner: unset/"owner", Discord: "public").
Do not duplicate page-building logic here — if this file ever needs more than these two lines,
that's a sign the logic belongs back in streamlit_app.py instead.
"""

from streamlit_app import run

run()

"""A bare `a() if x else st.caption(...)` line is a Streamlit "magic" expression: the returned DeltaGenerator gets
printed on the page as a wall of help text (seen on My Coach, Nov 8). Pages must use if/else statements instead."""
import ast
import glob


def test_no_bare_conditional_expressions_on_pages():
    bad = []
    for path in glob.glob("views/*.py") + ["Home.py", "streamlit_app.py"]:
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.IfExp):
                bad.append(f"{path}:{node.lineno}")
    assert not bad, f"bare conditional expressions render as magic output: {bad}"

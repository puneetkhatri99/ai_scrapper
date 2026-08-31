"""The browser feature: everything that opens a page.

recon.py     loads a url and reduces its DOM to a compact snapshot
executor.py  runs LLM-written code in a subprocess and validates what it returned
harness.py.tmpl  the wrapper that generated code is pasted into

The only package that imports playwright or spawns a subprocess.
"""

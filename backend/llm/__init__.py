"""The generation feature: the only package that talks to a model.

generate.py  builds the request, calls Gemini, extracts `def run(page)`
prompts.py   the frozen system prompt -- the cached half of every call
"""

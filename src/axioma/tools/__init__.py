"""axioma.tools — operator-facing CLI tools.

Each tool is invocable via `python -m axioma.tools.<name>`. They're
deliberately separate from the runtime entrypoint (`python -m axioma`) so
they can run against on-disk artifacts without booting the substrate.
"""

"""Browser mode: PDF Manager in the user's own browser, served from 127.0.0.1.

The same React interface and the same :class:`api.workflow.Workflow` as the
desktop window, reached through a small local HTTP API instead of pywebview:

* ``session``     Per-launch state the page refers to only by opaque IDs
                  (files, folders, downloads), staged uploads and the latest
                  job and OCR-install status the page polls.
* ``operations``  The explicit list of operations the page may call, each
                  validating its input before it reaches the workflow.
* ``server``      The loopback HTTP server: routing, the session cookie,
                  Host/Origin checks, size and time limits.
* ``launch``      Start-up and shut-down: one instance per user, readiness,
                  opening the default browser (app mode where it supports it).

Nothing in this package imports pywebview, Qt or pythonnet. See
docs/BROWSER_MODE.md.
"""

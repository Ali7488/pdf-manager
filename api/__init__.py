"""PDF Manager API layer: the bridge between the React UI and the converter.

This package is the middle of the three layers (decision F35):

* ``frontend/``: the React UI, shown in a pywebview window.
* ``api/`` (this package): everything the window needs from Python. It
  exposes :class:`api.bridge.Api` as ``window.pywebview.api``, converts the
  UI's camelCase JSON to the service layer's dataclasses and back, runs one
  job at a time, stores settings, saves results and writes the logs.
* ``converter/``: pure conversion logic with no UI or bridge code.

Modules:
    paths           Where the app, its bundled files, logs and settings live.
    logging_setup   Log files, log levels (dev vs production) and issue logging.
    settings_store  Loading, validating and atomically saving user settings.
    dto             camelCase JSON <-> service-layer dataclasses.
    jobs            The job manager: worker thread, progress, cancel, save, discard.
    bridge          The ``Api`` class exposed to JavaScript, events and drag and drop.
    app             Window creation and the ``main()`` entry point.
"""

# Shown in Settings ("About") and written to the log on start. Keep in sync with
# ``version`` in pyproject.toml (a test checks this). A constant, rather than
# reading pyproject.toml, so it also works in the packaged executable.
__version__ = "0.5.0"

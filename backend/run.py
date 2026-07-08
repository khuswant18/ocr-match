import os
from app import create_app
from app.workers.match_worker import start_match_worker

app = create_app()

if __name__ == "__main__":
    # Start the background match worker exactly once, in the process that
    # actually serves requests. The Werkzeug debug reloader execs this module
    # twice (a supervisor process + the reloaded child); only the child sets
    # WERKZEUG_RUN_MAIN. Starting it in both would give two workers — doubling
    # PaddleOCR memory and splitting the in-process cancel registry so /cancel
    # cannot reach a job running in the other process.
    #
    # NOTE: a future non-reloader WSGI entrypoint (waitress/gunicorn) imports
    # `app` from this module and never runs this block, so it must call
    # start_match_worker(app) itself.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_match_worker(app)
    app.run(debug=True, host="0.0.0.0", port=4333)
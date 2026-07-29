import os
from app import create_app
from app.workers.match_worker import start_match_worker
# from app.workers.psr_worker import start_psr_worker

app = create_app()

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_match_worker(app)
        # start_psr_worker(app)
    app.run(debug=True, host="0.0.0.0", port=4333)
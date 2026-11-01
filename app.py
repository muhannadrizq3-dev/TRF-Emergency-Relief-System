import os
import sys
import traceback

from flask import Flask

app = Flask(__name__)

try:
    from web_app import create_app
    create_app(app=app)
except Exception:
    startup_error = traceback.format_exc()
    print(startup_error, file=sys.stderr)
    reason = startup_error.strip().splitlines()[-1]

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def startup_failed(path):
        text = "TRF Emergency Relief could not start.\n\nError:\n" + reason
        return text, 500, {"Content-Type": "text/plain; charset=utf-8"}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))

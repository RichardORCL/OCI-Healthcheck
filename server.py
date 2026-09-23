"""OCI Health Check server.

Serves the static site and persists shared data. Every health check is a
JSON file in the healthcheck/ folder; its file name (without .json) is the
health check id used in the URLs below.

- GET  /api/healthchecks           lists the available health checks
  (id, title, description) by scanning healthcheck/*.json.
- POST /api/editor/verify          (editor password required) checks the
  password before the browser enables editor mode.
- POST /api/checklist/<id>         (editor password required) writes the
  checklist definition to healthcheck/<id>.json, so edits are shared. The
  file is created when it does not exist yet (new health check).
- POST /api/feedback/<id>          (open to everyone) stores anonymous
  feedback about a checklist item in data/feedback.json.
- GET  /api/feedback/<id>          (editor password required) returns all
  feedback for that health check.
- DELETE /api/feedback/<id>        (editor password required) removes one
  feedback entry.
  data/feedback.json itself is never served, so feedback stays invisible
  to regular users.

Editor password hash is read from config.json (see config.json.example).

Usage:  python server.py [port] [host]      (default port 8080, host 0.0.0.0)
"""

import hashlib
import json
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
HEALTHCHECK_DIR = ROOT / "healthcheck"
FEEDBACK_FILE = ROOT / "data" / "feedback.json"

# Health check ids are file names; keep them strictly to safe characters.
HEALTHCHECK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
API_WITH_ID_RE = re.compile(r"^/api/(checklist|feedback)/([^/]+)$")


def load_editor_password_hash():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        password_hash = data.get("editorPasswordHash")
        if isinstance(password_hash, str) and password_hash:
            return password_hash
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    raise SystemExit(
        f"Missing or invalid editorPasswordHash in {CONFIG_FILE}. "
        f"Copy config.json.example to config.json and set the SHA-256 hex digest "
        f"of your editor password."
    )


EDITOR_PASSWORD_HASH = load_editor_password_hash()

MAX_FEEDBACK_LENGTH = 5000
USER_TEXT_ERROR = (
    "Plain text only. HTML, code blocks, scripts and similar content are not allowed."
)

USER_TEXT_RULES = [
    (r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "Text contains invalid control characters."),
    (r"<\s*/?\s*[a-zA-Z][^>]*>", USER_TEXT_ERROR),
    (r"&lt;\s*/?\s*[a-zA-Z]", USER_TEXT_ERROR),
    (r"(?:^|[\s\"'(])javascript\s*:", USER_TEXT_ERROR),
    (r"(?:^|[\s\"'(])data\s*:", USER_TEXT_ERROR),
    (r"(?:^|[\s\"'(])vbscript\s*:", USER_TEXT_ERROR),
    (r"\bon[a-z]+\s*=", USER_TEXT_ERROR),
    (r"<\s*!\[CDATA\[", USER_TEXT_ERROR),
    (r"<%", USER_TEXT_ERROR),
    (r"<\?php", USER_TEXT_ERROR),
    (r"```", USER_TEXT_ERROR),
    (r"\beval\s*\(", USER_TEXT_ERROR),
    (r"\bnew\s+Function\s*\(", USER_TEXT_ERROR),
]

_user_text_patterns = [(re.compile(p, re.IGNORECASE), msg) for p, msg in USER_TEXT_RULES]


def validate_user_text(text):
    if not isinstance(text, str):
        return False, USER_TEXT_ERROR
    if len(text) > MAX_FEEDBACK_LENGTH:
        return False, f"Text is too long (maximum {MAX_FEEDBACK_LENGTH} characters)."
    for pattern, message in _user_text_patterns:
        if pattern.search(text):
            return False, message
    return True, ""


write_lock = threading.Lock()


def write_json_atomic(path, data):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_feedback():
    """Feedback store: { healthcheckId: { itemId: [entries] } }."""
    try:
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def healthcheck_file(healthcheck_id):
    """Path of a health check definition, or None if the id is unsafe."""
    if not HEALTHCHECK_ID_RE.match(healthcheck_id) or ".." in healthcheck_id:
        return None
    return HEALTHCHECK_DIR / f"{healthcheck_id}.json"


def list_healthchecks():
    """One entry per readable healthcheck/*.json, sorted by title."""
    result = []
    if not HEALTHCHECK_DIR.is_dir():
        return result
    for path in sorted(HEALTHCHECK_DIR.glob("*.json")):
        healthcheck_id = path.stem
        if not HEALTHCHECK_ID_RE.match(healthcheck_id):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data.get("categories"), list):
                raise ValueError("missing categories")
        except (OSError, ValueError, AttributeError) as err:
            print(f"Skipping {path.name}: {err}", file=sys.stderr)
            continue
        title = data.get("title")
        description = data.get("description")
        result.append({
            "id": healthcheck_id,
            "file": f"healthcheck/{path.name}",
            "title": title if isinstance(title, str) and title.strip() else healthcheck_id,
            "description": description if isinstance(description, str) else "",
        })
    result.sort(key=lambda hc: hc["title"].lower())
    return result


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # Nothing may be cached: visitors must always get current checklist,
        # styles and logic after an edit or an update of the tool.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ------------------------------ helpers ------------------------------

    def _clean_path(self):
        return self.path.split("?", 1)[0].split("#", 1)[0]

    def _editor_authorized(self):
        password = self.headers.get("X-Editor-Password", "")
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == EDITOR_PASSWORD_HASH

    def _read_body_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api_with_id(self, allow_new_checklist=False):
        """('checklist'|'feedback', id) for /api/<kind>/<id>, else None.
        Sends a 404 itself when the id is unsafe or unknown. With
        allow_new_checklist a checklist id without a file is accepted, so the
        editor can create a new health check."""
        match = API_WITH_ID_RE.match(self._clean_path())
        if not match:
            return None
        kind, healthcheck_id = match.groups()
        path = healthcheck_file(healthcheck_id)
        if path is None:
            self.send_error(404, "Invalid health check id")
            return "handled"
        if not path.is_file() and not (allow_new_checklist and kind == "checklist"):
            self.send_error(404, "Unknown health check")
            return "handled"
        return kind, healthcheck_id

    # ------------------------------- GET ---------------------------------

    def do_GET(self):
        path = self._clean_path()
        if path == "/config.json":
            self.send_error(403, "Configuration is not publicly available")
            return
        if path == "/data/feedback.json":
            self.send_error(403, "Feedback is only available through the editor")
            return
        if path == "/api/healthchecks":
            self._send_json(list_healthchecks())
            return
        target = self._api_with_id()
        if target == "handled":
            return
        if target is not None:
            kind, healthcheck_id = target
            if kind != "feedback":
                self.send_error(404)
                return
            if not self._editor_authorized():
                self.send_error(403, "Invalid editor password")
                return
            self._send_json(load_feedback().get(healthcheck_id, {}))
            return
        super().do_GET()

    def do_HEAD(self):
        path = self._clean_path()
        if path in ("/config.json", "/data/feedback.json"):
            self.send_error(403)
            return
        super().do_HEAD()

    # ------------------------------- POST --------------------------------

    def do_POST(self):
        path = self._clean_path()
        if path == "/api/editor/verify":
            self._post_editor_verify()
            return
        target = self._api_with_id(allow_new_checklist=True)
        if target == "handled":
            return
        if target is None:
            self.send_error(404)
            return
        kind, healthcheck_id = target
        if kind == "checklist":
            self._post_checklist(healthcheck_id)
        else:
            self._post_feedback(healthcheck_id)

    def _post_editor_verify(self):
        if self._editor_authorized():
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(403, "Invalid editor password")

    def _post_checklist(self, healthcheck_id):
        if not self._editor_authorized():
            self.send_error(403, "Invalid editor password")
            return
        try:
            data = self._read_body_json()
            if not isinstance(data.get("categories"), list):
                raise ValueError("missing categories")
        except (ValueError, KeyError, AttributeError, json.JSONDecodeError):
            self.send_error(400, "Invalid checklist JSON")
            return

        with write_lock:
            write_json_atomic(healthcheck_file(healthcheck_id), data)
        self.send_response(204)
        self.end_headers()

    def _post_feedback(self, healthcheck_id):
        try:
            data = self._read_body_json()
            item_id = data.get("itemId")
            text = data.get("text")
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValueError("missing itemId")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("missing text")
        except (ValueError, KeyError, AttributeError, json.JSONDecodeError):
            self.send_error(400, "Invalid feedback")
            return

        ok, message = validate_user_text(text.strip())
        if not ok:
            self._send_json({"error": message}, status=400)
            return

        entry = {
            "id": uuid.uuid4().hex,
            "text": text.strip()[:MAX_FEEDBACK_LENGTH],
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with write_lock:
            feedback = load_feedback()
            per_check = feedback.setdefault(healthcheck_id, {})
            per_check.setdefault(item_id.strip(), []).append(entry)
            write_json_atomic(FEEDBACK_FILE, feedback)
        self.send_response(204)
        self.end_headers()

    # ------------------------------ DELETE -------------------------------

    def do_DELETE(self):
        target = self._api_with_id()
        if target == "handled":
            return
        if target is None or target[0] != "feedback":
            self.send_error(404)
            return
        healthcheck_id = target[1]
        if not self._editor_authorized():
            self.send_error(403, "Invalid editor password")
            return

        try:
            data = self._read_body_json()
            item_id = data.get("itemId")
            entry_id = data.get("id")
            if not isinstance(item_id, str) or not isinstance(entry_id, str):
                raise ValueError("missing itemId or id")
        except (ValueError, KeyError, AttributeError, json.JSONDecodeError):
            self.send_error(400, "Invalid delete request")
            return

        with write_lock:
            feedback = load_feedback()
            per_check = feedback.get(healthcheck_id, {})
            entries = per_check.get(item_id, [])
            remaining = [e for e in entries if e.get("id") != entry_id]
            if len(remaining) == len(entries):
                self.send_error(404, "Feedback entry not found")
                return
            if remaining:
                per_check[item_id] = remaining
            else:
                per_check.pop(item_id, None)
            if per_check:
                feedback[healthcheck_id] = per_check
            else:
                feedback.pop(healthcheck_id, None)
            write_json_atomic(FEEDBACK_FILE, feedback)

        self.send_response(204)
        self.end_headers()


def main():
    HEALTHCHECK_DIR.mkdir(exist_ok=True)
    FEEDBACK_FILE.parent.mkdir(exist_ok=True)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"OCI Health Check serving on http://{host}:{port} (Ctrl+C to stop)")
    print(f"Health checks: {', '.join(hc['id'] for hc in list_healthchecks()) or '(none found)'}")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""In-process fake of the two Woodpecker endpoints the agent switch uses.

GET /api/agents and PATCH /api/agents/{id}, bearer-token checked, backed by a
mutable dict so tests can move the clock-independent state around. Records every
accepted PATCH and whether it left no agent able to take an unlabeled workflow (the invariant
the switch must never break).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeWoodpecker:
    def __init__(self, agents: list[dict], token: str = "tok"):
        self.agents = {a["id"]: dict(a) for a in agents}
        self.require_token = token
        self.patch_log: list[tuple[int, dict]] = []
        self.invariant_violations: list[tuple[int, dict]] = []
        self._fail: dict[str, int] = {}
        self._server: ThreadingHTTPServer | None = None

    @staticmethod
    def accepts_unlabeled(agent: dict) -> bool:
        """Would this agent take a workflow with no labels? A `!key` filter
        requires the label, so it rejects unlabeled work."""
        return not agent["no_schedule"] and not any(
            k.startswith("!") for k in agent["filters"]
        )

    def fail_next(self, method: str, status: int) -> None:
        self._fail[method] = status

    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, status: int, payload=None):
                body = json.dumps(payload if payload is not None else {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _gate(self, method: str) -> bool:
                if self.headers.get("Authorization") != f"Bearer {outer.require_token}":
                    self._reply(401, {"error": "bad token"})
                    return False
                if method in outer._fail:
                    self._reply(outer._fail.pop(method), {"error": "injected"})
                    return False
                return True

            def do_GET(self):
                if self._gate("GET") and self.path == "/api/agents":
                    self._reply(200, list(outer.agents.values()))

            def do_PATCH(self):
                if not self._gate("PATCH"):
                    return
                agent_id = int(self.path.rsplit("/", 1)[1])
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                a = outer.agents[agent_id]
                a["name"] = body["name"]
                a["no_schedule"] = body["no_schedule"]
                a["filters"] = body["filters"]
                outer.patch_log.append((agent_id, body))
                if not any(outer.accepts_unlabeled(x) for x in outer.agents.values()):
                    outer.invariant_violations.append((agent_id, body))
                self._reply(200, a)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

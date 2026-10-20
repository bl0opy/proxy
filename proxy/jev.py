import http.client
import json
import os

HOST = "api.typesafe.ai"
PATH = "/v1/systemone"
MODEL = "jev-1.14.0"


class JevError(RuntimeError):
    pass


class Jev:
    def __init__(self, api_key: str | None = None, model: str = MODEL, timeout: float = 5.0):
        self._key = api_key or os.environ["JEV_API_KEY"]
        self._model = model
        self._timeout = timeout
        self._conn: http.client.HTTPSConnection | None = None

    def _connection(self) -> http.client.HTTPSConnection:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(HOST, timeout=self._timeout)
        return self._conn

    def warm(self):
        self._connection().connect()

    def ask(self, state: str, questions: dict) -> dict:
        body = json.dumps({"model": self._model, "state": state, "questions": questions})
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        for attempt in range(2):
            conn = self._connection()
            try:
                conn.request("POST", PATH, body, headers)
                resp = conn.getresponse()
                data = resp.read()
            except (http.client.HTTPException, OSError):
                conn.close()
                self._conn = None
                if attempt:
                    raise
                continue
            if resp.status != 200:
                raise JevError(f"{resp.status}: {data[:300].decode(errors='replace')}")
            return json.loads(data)
        raise JevError("unreachable")

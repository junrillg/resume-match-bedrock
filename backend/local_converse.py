"""Local HTTP Converse contract; deterministic evidence, not an AWS/model emulator."""
import json
import os
import socket
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from matching.services import (InvalidInput, correlation_ids, literal_evidence,
                               read_requirements, read_resume)
from matching.telemetry import emit

MAX_REQUEST_BYTES = 220_000


class ConverseHandler(BaseHTTPRequestHandler):
    # One bounded request at a time is sufficient for this single-worker local counterpart.
    timeout = 5

    def setup(self):
        super().setup()
        self.connection.settimeout(self.timeout)

    def log_message(self, format, *args):
        pass  # Request paths, headers and bodies never enter provider logs.

    def reply(self, status, payload, error_type=None):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if error_type:
            self.send_header("x-amzn-errortype", error_type)
        self.send_header("x-amzn-requestid", str(uuid.uuid4()))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 404, {"status": "ready" if self.path == "/health" else "unavailable"})

    def do_POST(self):
        try:
            if self.path != "/model/local-evidence-v1/converse" or self.headers.get("Transfer-Encoding"):
                raise InvalidInput()
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise InvalidInput()
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise InvalidInput()
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) - {"system", "messages", "inferenceConfig", "requestMetadata"} or not {"system", "messages", "inferenceConfig"} <= set(body):
                raise InvalidInput()
            if body["inferenceConfig"] != {"maxTokens": 4096, "temperature": 0}:
                raise InvalidInput()
            system, messages = body["system"], body["messages"]
            if not isinstance(system, list) or len(system) != 1 or set(system[0]) != {"text"} or not isinstance(system[0]["text"], str):
                raise InvalidInput()
            if not isinstance(messages, list) or len(messages) != 1 or set(messages[0]) != {"role", "content"} or messages[0]["role"] != "user":
                raise InvalidInput()
            content = messages[0]["content"]
            if not isinstance(content, list) or len(content) != 1 or set(content[0]) != {"text"}:
                raise InvalidInput()
            data = json.loads(content[0]["text"])
            if not isinstance(data, dict) or set(data) != {"requested_skills", "resume_text"} or not isinstance(data["requested_skills"], list) or not isinstance(data["resume_text"], str):
                raise InvalidInput()
            text = read_resume(data["resume_text"], None)
            requirements = read_requirements(json.dumps([{"skill": skill, "weight": 1} for skill in data["requested_skills"]]))
            extracted = literal_evidence(text, requirements)
        except (ValueError, TypeError, KeyError, AttributeError, socket.timeout):
            self.reply(400, {"message": "Invalid local Converse request."}, "ValidationException")
            return
        emit("provider.completed", **correlation_ids(body.get("requestMetadata")), stage="provider", status="succeeded")
        self.reply(200, {"output": {"message": {"role": "assistant", "content": [{"text": json.dumps(extracted, ensure_ascii=False)}]}},
                         "stopReason": "end_turn", "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                         "metrics": {"latencyMs": 0}})


if __name__ == "__main__":
    import django
    django.setup()
    HTTPServer(("0.0.0.0", 8090), ConverseHandler).serve_forever()

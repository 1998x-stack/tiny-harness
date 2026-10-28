# tiny_harness/_persist.py
"""JSONL-based session persistence for tiny-harness conversations."""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


class SessionStore:
    def __init__(self, base_dir: str | None = None):
        self._base = Path(base_dir or os.path.join(os.path.expanduser("~"), ".tiny-harness", "sessions"))
        self._base.mkdir(parents=True, exist_ok=True)

    def new_session(self) -> str:
        sid = uuid.uuid4().hex[:12]
        return sid

    def save_turn(self, session_id: str, chat_id: int, role: str,
                  content: str | None = None,
                  tool_calls: list | None = None,
                  tool_results: list | None = None,
                  token_usage: dict | None = None,
                  model: str | None = None,
                  iteration: int | None = None,
                  metadata: dict | None = None) -> None:
        record = {
            "session_id": session_id,
            "chat_id": chat_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
        }
        if content is not None:
            record["content"] = content
        if tool_calls:
            record["tool_calls"] = [
                {"id": tc.get("id", ""), "name": tc["name"], "arguments": tc.get("arguments", {})}
                if isinstance(tc, dict) else {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in tool_calls
            ]
        if tool_results:
            record["tool_results"] = [
                {"id": tr.get("id") or tr.get("tool_call_id", ""), "content": str(tr.get("content", ""))}
                if isinstance(tr, dict) else {"id": tr.tool_call_id, "content": str(tr.content)}
                for tr in tool_results
            ]
        if token_usage:
            record["token_usage"] = token_usage
        if model:
            record["model"] = model
        if iteration is not None:
            record["iteration"] = iteration
        if metadata:
            record["metadata"] = metadata

        filepath = self._session_path(session_id)
        fd = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.chmod(filepath, 0o600)

    def replace_turns(self, session_id: str, records: list[dict]) -> None:
        """Atomically replace a complete conversation snapshot (idempotent /save)."""
        target = self._session_path(session_id)
        fd, temp_name = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=self._base)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                for record in records:
                    file.write(json.dumps(record, ensure_ascii=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)

    def load_session(self, session_id: str) -> list[dict]:
        filepath = self._session_path(session_id)
        if not filepath.exists():
            return []
        records = []
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Crash-safe loading: ignore only an incomplete trailing record.
                if index == len(lines) - 1:
                    break
                raise
        return records

    def list_sessions(self) -> list[dict]:
        sessions = []
        for fpath in sorted(self._base.glob("*.jsonl"), key=os.path.getmtime, reverse=True):
            sid = fpath.stem
            records = self.load_session(sid)
            if not records:
                continue
            first = records[0]
            last = records[-1]
            sessions.append({
                "session_id": sid,
                "created": first.get("timestamp", ""),
                "updated": last.get("timestamp", ""),
                "turns": len(records),
                "model": first.get("model", "unknown"),
                "file": str(fpath),
            })
        return sessions

    def delete_session(self, session_id: str) -> bool:
        filepath = self._session_path(session_id)
        if filepath.exists():
            os.remove(filepath)
            return True
        return False

    def export_session(self, session_id: str) -> dict:
        records = self.load_session(session_id)
        return {
            "session_id": session_id,
            "turns": len(records),
            "records": records,
        }

    def _session_path(self, session_id: str) -> Path:
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self._base / f"{safe_id}.jsonl"

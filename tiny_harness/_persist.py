# tiny_harness/_persist.py
"""JSONL-based session persistence for tiny-harness conversations."""
import json
import os
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
                {"name": tc["name"], "arguments": tc.get("arguments", {})}
                if isinstance(tc, dict) else {"name": tc.name, "arguments": tc.arguments}
                for tc in tool_calls
            ]
        if tool_results:
            record["tool_results"] = [
                {"id": tr.get("tool_call_id", ""), "content": str(tr.get("content", ""))[:200]}
                if isinstance(tr, dict) else {"id": tr.tool_call_id, "content": str(tr.content)[:200]}
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
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_session(self, session_id: str) -> list[dict]:
        filepath = self._session_path(session_id)
        if not filepath.exists():
            return []
        records = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
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

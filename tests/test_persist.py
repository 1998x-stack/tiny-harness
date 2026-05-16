# tests/test_persist.py
import tempfile
from tiny_harness._persist import SessionStore


def test_new_session_creates_id():
    store = SessionStore()
    sid = store.new_session()
    assert len(sid) == 12
    assert sid.isalnum()


def test_save_and_load_turn():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid = store.new_session()

        store.save_turn(sid, chat_id=1, role="user", content="Hello", model="deepseek-chat")
        store.save_turn(sid, chat_id=2, role="assistant", content="Hi!", token_usage={"input": 10, "output": 5})

        records = store.load_session(sid)
        assert len(records) == 2
        assert records[0]["role"] == "user"
        assert records[0]["content"] == "Hello"
        assert records[0]["chat_id"] == 1
        assert records[1]["role"] == "assistant"
        assert records[1]["token_usage"] == {"input": 10, "output": 5}


def test_save_turn_with_tool_calls():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid = store.new_session()

        store.save_turn(sid, chat_id=1, role="assistant", content="Let me check",
                        tool_calls=[{"name": "read_file", "arguments": {"path": "/tmp/x"}}],
                        tool_results=[{"tool_call_id": "tc1", "content": "file content here"}])

        records = store.load_session(sid)
        assert len(records) == 1
        assert len(records[0]["tool_calls"]) == 1
        assert records[0]["tool_calls"][0]["name"] == "read_file"
        assert len(records[0]["tool_results"]) == 1


def test_list_sessions():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid1 = store.new_session()
        sid2 = store.new_session()

        store.save_turn(sid1, 1, "user", "a")
        store.save_turn(sid2, 1, "user", "b")
        store.save_turn(sid2, 2, "assistant", "c")

        sessions = store.list_sessions()
        assert len(sessions) == 2
        s1 = next(s for s in sessions if s["session_id"] == sid1)
        s2 = next(s for s in sessions if s["session_id"] == sid2)
        assert s1["turns"] == 1
        assert s2["turns"] == 2


def test_delete_session():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid = store.new_session()
        store.save_turn(sid, 1, "user", "test")
        assert store.delete_session(sid) is True
        assert len(store.load_session(sid)) == 0


def test_delete_nonexistent_session():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        assert store.delete_session("nonexistent") is False


def test_export_session():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid = store.new_session()
        store.save_turn(sid, 1, "user", "test", model="deepseek-chat")
        exported = store.export_session(sid)
        assert exported["session_id"] == sid
        assert exported["turns"] == 1
        assert len(exported["records"]) == 1


def test_save_turn_with_iteration():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid = store.new_session()
        store.save_turn(sid, 1, "assistant", "ok", iteration=3, metadata={"workspace": "/tmp"})
        records = store.load_session(sid)
        assert records[0]["iteration"] == 3
        assert records[0]["metadata"]["workspace"] == "/tmp"


def test_timestamp_is_isoformat():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(base_dir=d)
        sid = store.new_session()
        store.save_turn(sid, 1, "user", "hi")
        records = store.load_session(sid)
        assert "T" in records[0]["timestamp"]
        assert records[0]["timestamp"].endswith("Z") or "+" in records[0]["timestamp"]


def test_default_base_dir():
    store = SessionStore()
    assert ".tiny-harness" in str(store._base)

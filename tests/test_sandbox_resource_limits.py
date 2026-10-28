"""Resource limits are validated and forwarded without shell interpolation."""
import pytest

from tiny_harness._sandbox import SandboxUnavailable, build_bubblewrap_argv


@pytest.mark.parametrize("keyword,value", [
    ("cpu_seconds", 0), ("cpu_seconds", -10), ("cpu_seconds", True),
    ("memory_mb", 0), ("memory_mb", 16385), ("memory_mb", "1024"),
    ("file_mb", -1), ("file_mb", 1025), ("file_mb", 1.5),
])
def test_resource_caps_reject_invalid_values(tmp_path, monkeypatch, keyword, value):
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/" + name)
    args = {"cpu_seconds": 30, "memory_mb": 1024, "file_mb": 32}
    args[keyword] = value
    with pytest.raises(SandboxUnavailable, match=keyword):
        build_bubblewrap_argv("true", workspace=str(tmp_path), cwd=None, **args)


def test_resource_caps_are_structured_argv(tmp_path, monkeypatch):
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/" + name)
    marker = "echo --as=untrusted; printf 'data'"
    argv = build_bubblewrap_argv(
        marker, workspace=str(tmp_path), cwd=None,
        cpu_seconds=7, memory_mb=256, file_mb=4,
    )
    assert "--cpu=7" in argv
    assert "--as=268435456" in argv
    assert "--fsize=4194304" in argv
    assert argv[-3:] == ["/bin/sh", "-c", marker]


def test_missing_prlimit_blocks_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/bwrap" if name == "bwrap" else None)
    with pytest.raises(SandboxUnavailable, match="prlimit"):
        build_bubblewrap_argv("true", workspace=str(tmp_path), cwd=None)

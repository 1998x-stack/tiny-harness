# Linux Shell Isolation / Bubblewrap

The built-in Shell skill supports an **optional**, Linux-only `bubblewrap`
execution mode. It is opt-in and does not change other tool handlers or
the default unsandboxed behavior.

## Setup

Install `bubblewrap` and util-linux `prlimit` from the operating system's
package manager, and verify the host permits unprivileged user namespaces.

```bash
tiny-harness \
  --workspace /path/to/disposable-workspace \
  --provider deepseek \
  --skills files,shell \
  --shell-sandbox bubblewrap \
  --sandbox-cpu-seconds 30 \
  --sandbox-memory-mb 1024 \
  --sandbox-file-mb 32
```

Shell retains the usual HITL approvals. Disabling HITL still requires a
separate explicit `--allow-unsafe-shell` option; the sandbox is not a
substitute for user authorization.

## Namespace and filesystem contract

- `--unshare-all` isolates namespaces, including network and PID.
  There is **no** `--share-net` fallback.
- `--tmpfs /` starts with an empty root. Selected system binary and library
  directories (`/usr`, `/bin`, `/lib`, etc.) are mounted **read-only**.
  No blanket `--ro-bind / /` or `--ro-bind /etc /etc` is used.
- Only the explicitly configured workspace is writable as
  `/workspace`. Relative `cwd` is mapped inside that mount after
  canonicalization. `/tmp` is a private tmpfs.
- The environment is cleared; only PATH, HOME, TMPDIR and LANG are set
  inside the sandbox. Outside API keys are not forwarded.
- The host `bwrap` executable and `prlimit` are resolved from the system
  binary directories, not from the working directory or arbitrary PATH.

## Resource constraints

The `prlimit` wrapper imposes `RLIMIT_CPU`, `RLIMIT_AS`, and
`RLIMIT_FSIZE`. Defaults: CPU 30 seconds, virtual address space 1024 MiB,
file size 32 MiB. They are inherited by child processes.

**Important:** These limits are *per process* and are **not aggregate cgroup
CPU or memory quotas**. The executor's existing timeout limits wall-clock
duration; its output cap limits retained output. `RLIMIT_AS` caps virtual
address space, which is not the same as RSS. The sandbox also does not limit
total disk writes across multiple files or processes.

## Unsupported cases / failure

If the OS is not Linux, the sandbox binaries are unavailable, the workspace
is invalid, the Linux kernel blocks namespace creation, or the sandbox
launcher returns an error, the operation fails. There is **no automatic
retry as an unsandboxed shell**.

The legacy direct `run_command()` Python helper remains unsandboxed;
the backend applies only to the Shell skill's registered
`run_command_async` handler.

## Limitations and validation

- Workspace contents and symlinks remain untrusted. The mount boundary
  does not protect credentials already stored **inside** the workspace.
- This does not sandbox custom third-party Python tool handlers, and it
  does not claim to protect against kernel vulnerabilities or bind-mount
  time-of-check/time-of-use races.
- Binary compatibility depends on which trusted system directories are
  exposed. Programs requiring host services, sockets, device access,
  arbitrary `/opt` paths, or networking may fail intentionally.
- The CI Python test matrix checks launcher construction, explicit opt-in,
  missing-binary fail-closed behavior, and resource flags. The separate
  **Linux bubblewrap probe** job installs bwrap and attempts an actual
  isolation smoke test. That test explicitly **SKIPs** when the runner
  cannot create unprivileged user namespaces. A green CI result with a
  skip does not establish successful real isolation; inspect job logs.

### Production follow-up

A production multi-tenant deployment still needs cgroup v2 aggregate quotas,
verified seccomp/AppArmor/SELinux policy, process identity isolation,
safe bind-mount handling, independent credentials, and dedicated
platform-specific integration tests.

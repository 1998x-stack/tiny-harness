# OCI / Docker Shell Sandbox

The built-in async Shell skill has three execution modes:

| `shell_sandbox` | Behavior | Isolation claim |
|---|---|---|
| `off` (default) | Host subprocess, requires HITL by default | **No OS isolation** |
| `bubblewrap` | Linux user/mount/network namespaces, per-process rlimits | Host-dependent; real namespace test may skip in CI |
| `docker` | Linux Docker OCI container, cgroup resource caps, network none | Real Docker integration test required and passing on Ubuntu CI |

The Docker backend applies **only** to the registered async
`run_command` Shell skill. File and third-party Python tools run on the
host and are not sandboxed by this setting.

## Configure a trusted, pre-pulled immutable image

Choose and audit an image suitable for the commands you intend to run.
For a local demonstration with Alpine:

```bash
docker pull alpine:3.20
docker image inspect --format '{{index .RepoDigests 0}}' alpine:3.20
```

Copy the resulting `repository@sha256:...` into `--sandbox-image`.
Digest pinning ensures the selected image cannot silently change during
execution. The agent **never pulls images** (`--pull=never`). Supply
only images you trust; the daemon's image store and Docker access are
trusted host components.

```bash
tiny-harness \
  --provider deepseek \
  --workspace /absolute/path/to/disposable-project \
  --skills files,shell \
  --shell-sandbox docker \
  --sandbox-image 'alpine@sha256:<your_64_hex_digest>' \
  --sandbox-cpus 1.0 \
  --sandbox-memory-mb 1024 \
  --sandbox-pids-limit 64
```

The image digest in the example is a **placeholder**, not a usable pin.
Set `--sandbox-image` to the actual inspected `repository@sha256`
reference. No-hitl Shell still requires the separate explicit
`--allow-unsafe-shell` opt-in; keep HITL enabled for regular use.

## Runtime behavior

The builder uses a fixed Docker CLI argv and passes the model's command
only as a final argument to `/bin/sh -c` **inside** the container:

- `--network=none` blocks container external networking.
- `--read-only` makes the image root filesystem read-only, with a private
  bounded `/tmp` tmpfs.
- `--mount type=bind,...,target=/workspace` exposes exactly the selected
  host project as the writable workspace. All cwd paths must remain inside
  it, and system root directories are rejected.
- `--cap-drop=ALL` plus `--security-opt=no-new-privileges:true`
  removes ambient capabilities and blocks gaining additional privileges.
- `--user uid:gid` uses the non-root host identity (root host user is
  rejected) to preserve project file ownership.
- `--memory` and `--memory-swap` impose container memory/swap ceilings;
  `--cpus` sets aggregate CPU quota; `--pids-limit` limits container
  processes. These are **cgroup** limits across container processes,
  unlike Bubblewrap's inherited per-process rlimits.
- Each call receives a generated unique name, a private Docker CLI config
  directory, and is cleaned with daemon-side `docker rm -f` even after
  timeout or task cancellation. Failures never fall back to host Shell.

The existing Shell output cap and wall-clock timeout still apply.
The Bubblewrap-only `sandbox_cpu_seconds` and `sandbox_file_mb`
flags do not create Docker disk-usage quotas.

## Real validation

GitHub CI job `Real OCI cgroup and network isolation` installs package
dependencies, pulls the test image, resolves an immutable image digest,
then executes the Shell skill **inside a real container**. It asserts:

1. The container's cgroup memory and PID limits match the requested values.
2. The container has no ordinary network routes.
3. The host file outside the selected workspace is not visible.
4. Writing into the designated workspace succeeds.
5. Timed-out and cancelled jobs leave no running/retained named container.

Unlike Bubblewrap's optional smoke, the Docker job is **mandatory** and
fails if the required image environment is missing. Its passing state is
evidence for this tested GitHub runner configuration, not universal proof.

## Trust boundary and remaining risks

**Docker daemon access is highly privileged**. Never mount
`/var/run/docker.sock`, pass daemon credentials to models, or expose the
Docker API to untrusted users. This implementation targets a trusted local
daemon, not hostile multi-tenant compute, rootless Kubernetes, or remote
Docker daemons.

Other risks remain: workspace contents and executable image code must be
trusted appropriately; volume paths could be swapped by concurrent host
processes; Docker daemon and kernel vulnerabilities are out of scope;
system-default seccomp profiles are daemon dependent; the shared host daemon
is not an independent security trust domain.

Production-grade multi-tenant use needs a dedicated daemon/VM per tenant,
audited images, verified seccomp/AppArmor/SELinux profiles, identity mapping
and tighter filesystem protections, policy gates for *every* tool handler,
and integration tests on each supported host and kernel.

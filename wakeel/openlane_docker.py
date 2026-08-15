"""
Resolves the ACTUAL docker invocation OpenLane needs, by asking its own
Makefile for it -- instead of hand-reconstructing `docker run` flags
(PDK_OPTS, DOCKER_OPTIONS, image tag, arch suffix) in Python, which would
require guessing at Python helper scripts (env.py, get_tag.py,
current_platform.py) whose output can change across OpenLane versions.

`make -n mount` (dry-run) prints the fully-resolved shell command the real
`mount` target would execute -- every flag already computed, every
variable already substituted. This module runs that, parses out the
`docker run ...` line, and swaps its trailing `-ti <image>` (interactive
shell) for `<image> ./flow.tcl -design <name> ...` (a real, non-interactive
flow invocation) -- reusing 100% of OpenLane's own resolved configuration
instead of reimplementing any of it.

This is resolved fresh on every real run (not cached), so it stays correct
even if the user updates OpenLane, rebuilds the container, or changes PDKs
-- there's nothing here to go stale the way a hand-copied command would.
"""
from __future__ import annotations
import asyncio
import re


class OpenLaneDockerResolutionError(Exception):
    pass


_DOCKER_RUN_RE = re.compile(r"(docker run .+?)(?:\s*-ti\s+)(\S+)\s*$", re.DOTALL)


async def resolve_flow_command(openlane_path: str, design: str, extra_env_exports: str = "") -> str:
    """Runs `make -n mount` inside openlane_path, extracts the real
    resolved `docker run ...` invocation, and returns a full shell command
    that runs `./flow.tcl -design <design>` non-interactively inside that
    exact container -- same image, same PDK/std-cell flags, same volume
    mounts the Makefile itself would use for `make mount`.
    """
    proc = await asyncio.create_subprocess_shell(
        f"cd {_shquote(openlane_path)} && make -n mount",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode("utf-8", errors="ignore")

    if proc.returncode != 0 or "docker run" not in output:
        raise OpenLaneDockerResolutionError(
            f"`make -n mount` did not produce a docker run command (rc={proc.returncode}). "
            f"stderr: {stderr.decode('utf-8', errors='ignore')[:500]}. "
            f"This means the Makefile's 'mount' target isn't available or behaves differently "
            f"than expected on this install -- needs a real look, not a guessed fallback."
        )

    # `make -n` may print the recipe across multiple echoed lines (one per
    # backslash-continuation) or already-joined depending on make version;
    # normalize line continuations before searching.
    joined = re.sub(r"\\\s*\n\s*", " ", output)

    m = _DOCKER_RUN_RE.search(joined)
    if not m:
        raise OpenLaneDockerResolutionError(
            f"Found 'docker run' in `make -n mount` output but couldn't isolate the "
            f"trailing '-ti <image>' pattern to replace -- the Makefile's mount recipe "
            f"may not match the expected `... -ti $(IMAGE)` tail. Raw output:\n{joined[:1000]}"
        )

    docker_prefix, image = m.group(1).strip(), m.group(2).strip()

    # Non-interactive: run flow.tcl directly instead of dropping into a
    # shell (-ti). extra_env_exports lets callers still set the titanium
    # thread-pinning flags etc. INSIDE the container's shell invocation.
    inner_cmd = f"{extra_env_exports}./flow.tcl -design {_shquote(design)} < /dev/null"
    return f"cd {_shquote(openlane_path)} && {docker_prefix} {image} bash -c {_shquote(inner_cmd)}"


def _shquote(s: str) -> str:
    import shlex
    return shlex.quote(s)

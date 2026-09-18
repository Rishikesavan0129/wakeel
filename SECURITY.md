# Security Policy

Wakeel shells out to Docker and to local OpenLane/ORFS installs based on
design names and parameters partly derived from user-supplied prompts, so
injection and path-handling issues are treated as security-relevant, not
just bugs.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a suspected security
problem. Instead, open a private security advisory via GitHub's
"Report a vulnerability" flow on this repo (Security tab → Report a
vulnerability), or contact the maintainer directly if that's unavailable.

Include:
- What input triggers it (a specific prompt, sweep config, or design
  name/path).
- What you observed vs. what you'd expect a safe implementation to do.
- Whether you believe it's exploitable locally only, or also relevant to
  someone running `wakeel_api.py` as a shared/networked service.

## Scope notes for reviewers

A few things worth knowing about the current design, so a report can be
triaged against what's already a deliberate mitigation vs. a gap:

- **Design/module names are sanitized** (`sanitize_identifier()` in
  `wakeel/orchestrator.py`) to `^[A-Za-z0-9_]+$` before they're ever
  interpolated into a shell command, and individual shell arguments are
  additionally passed through `shlex.quote()`. A report showing a way
  around this sanitization (e.g. a value that passes the regex but still
  breaks out of the intended command context) is high priority.
- Subprocess invocation still goes through `asyncio.create_subprocess_shell`
  (not `_exec`) because the underlying flow commands are shell pipelines
  (env exports, `&&` chains). If you find a path where an *unsanitized*
  value reaches that shell string, that's a real finding.
- **The loose-RTL auto-stage path** (`design_discovery.find_loose_rtl`/
  `stage_design`) only ever searches roots explicitly listed in
  `WAKEEL_RTL_SEARCH_ROOTS` — never an unbounded filesystem crawl — and
  copies (never symlinks or references in place) into the target engine's
  design root, refusing outright if a folder already exists there. A
  report showing this searching outside the configured roots, or writing
  into an existing folder, is high priority.
- `wakeel_api.py` is built to run as a local, single-user gateway (see
  the per-design `asyncio.Lock` note in `CHANGELOG_v3.md` — it's
  in-process only, not a distributed lock). It has not been hardened for
  exposure as a multi-tenant or public-internet service, and doing so is
  out of scope for the current architecture without further review —
  please flag if you're deploying it that way and want to help fix that.
- `WAKEEL_LOCAL_LLM_URL`, if pointed at anything other than localhost,
  will send config/error-log content to that endpoint (see
  `wakeel/local_llm.py`) — this is by design for the optional local-model
  fallback, but worth knowing if you're auditing data flow.

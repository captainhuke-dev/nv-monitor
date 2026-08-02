# Process Manager 9001 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Tailscale-scoped web Process Manager on port 9001 that inventories every readable Linux process, labels system processes with explicit reasons, and supports guarded stop/force-stop actions without modifying the existing nv-monitor.c hot path.

**Architecture:** Add an independent Python service under process_manager/. It reads process metadata from /proc through psutil, augments GPU memory from nvidia-smi when available, classifies each row as SYSTEM or USER, and exposes a small authenticated HTTP API plus a browser UI. The controller uses PID start-time fingerprints, refuses to stop itself/PID 1/kernel threads, requires explicit confirmation for other system processes, writes JSONL audit records outside Git, and defaults to loopback binding; a Tailscale address must be supplied explicitly for remote access.

**Tech Stack:** Python 3.12, standard-library http.server/HTML, psutil>=5.9,<6, unittest, and optional nvidia-smi GPU enrichment.

## Global Constraints

- Do not modify nv-monitor.c or its zero-allocation per-frame behavior.
- Local code path: /home/mctdgx01/projects/nv-monitor.
- Default API port: 9001.
- Default bind address: 127.0.0.1; reject wildcard binds unless an explicit unsafe override is supplied.
- API authentication: require Authorization: Bearer <PROCESS_MANAGER_TOKEN> for process data and actions; GET /healthz is the only unauthenticated endpoint.
- System label rules: SYSTEM when UID is 0, PID is 1, the process is a kernel thread, or its cgroup is system.slice/init.scope; otherwise USER.
- System reasons must be returned as machine-readable values and human-readable labels.
- Protected targets: the manager's own PID, PID 1, and kernel threads cannot be stopped from the API.
- Other SYSTEM targets require confirm_system=true; force-stop requires force=true.
- Every stop attempt must verify PID, creation time, and current classification immediately before signaling.
- Audit logs must be written outside Git, defaulting to ~/.local/state/nv-process-manager/audit.jsonl.
- The source checkout does not install or start the privileged service implicitly; provide a hardened unit and explicit enable-at-boot instructions.
- All new production behavior must have a test written and observed failing before implementation.

---

### Task 1: Define process classification and serialization

**Files:**
- Create: process_manager/__init__.py.
- Create: process_manager/models.py.
- Create: tests/test_models.py.

**Interfaces:**
- Produces SystemReason values: root, pid1, kernel_thread, systemd_service.
- Produces ProcessRecord with fields pid, ppid, uid, user, name, cmdline, status, cpu_percent, rss_bytes, gpu_memory_bytes, create_time, pgid, is_system, system_reasons, protected.
- Produces ProcessRecord.to_dict() with stable JSON keys and classification equal to SYSTEM or USER.

- [ ] Step 1: Write failing classification tests.

Test that UID 0 is SYSTEM with reason root, PID 1 is protected with reason pid1, a bracketed empty-command process is SYSTEM with reason kernel_thread, a system.slice cgroup adds systemd_service, and a normal non-root process is USER.

- [ ] Step 2: Run the focused tests and verify the expected missing-module failure.

Run: python3 -m unittest -v tests.test_models
Expected: FAIL because process_manager.models does not exist yet.

- [ ] Step 3: Implement the minimal data model and classifier.

Implement immutable dataclasses and pure classification helpers. Keep reason ordering deterministic: pid1, kernel_thread, root, systemd_service.

- [ ] Step 4: Run the focused tests.

Run: python3 -m unittest -v tests.test_models
Expected: PASS with no warnings.

### Task 2: Collect all readable processes and optional GPU memory

**Files:**
- Create: process_manager/gpu.py.
- Create: process_manager/collector.py.
- Create: tests/test_gpu.py.
- Create: tests/test_collector.py.

**Interfaces:**
- parse_gpu_memory_csv(text: str) -> dict[int, int] parses nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits.
- collect_processes(gpu_lookup=None, skip_pids=frozenset()) -> list[ProcessRecord] returns readable processes sorted by pid, never aborting the whole snapshot because one process exits or denies access.
- read_cgroup(path: str) -> str returns an empty string for missing/unreadable files.

- [ ] Step 1: Write failing GPU parser tests.

Use hand-derived CSV fixtures for two PIDs, [N/A], blank lines, malformed rows, and duplicate PIDs. Assert the exact resulting integer-byte map.

- [ ] Step 2: Run the focused GPU tests.

Run: python3 -m unittest -v tests.test_gpu
Expected: FAIL because process_manager.gpu does not exist.

- [ ] Step 3: Implement the parser and command wrapper.

Implement pure parsing first, then a short-timeout subprocess.run wrapper that returns an empty map when nvidia-smi is unavailable or fails. Never invoke a shell.

- [ ] Step 4: Run the GPU tests.

Run: python3 -m unittest -v tests.test_gpu
Expected: PASS.

- [ ] Step 5: Write failing collector tests.

Exercise the real current process table and assert that the result contains the test runner PID, every returned record has a classification, and one inaccessible/vanished process cannot make collection raise.

- [ ] Step 6: Run the collector tests.

Run: python3 -m unittest -v tests.test_collector
Expected: FAIL because collect_processes is not implemented.

- [ ] Step 7: Implement process collection.

Use psutil.process_iter with guarded per-process reads, os.getpgid where permitted, /proc/<pid>/cgroup for systemd classification, and gpu_lookup.get(pid) for optional GPU bytes. Truncate command lines to a fixed display limit while retaining the executable name.

- [ ] Step 8: Run collector and model tests.

Run: python3 -m unittest -v tests.test_models tests.test_gpu tests.test_collector
Expected: PASS.

### Task 3: Implement guarded stop policy and audit logging

**Files:**
- Create: process_manager/actions.py.
- Create: tests/test_actions.py.

**Interfaces:**
- StopRequest fields: pid, expected_create_time, confirm_system, force.
- StopResult fields: pid, signal, status, message.
- stop_process(request, audit_log_path, manager_pid=None) -> StopResult.
- Error responses use stable codes: missing_fingerprint, pid_reused, manager_process, protected_process, system_confirmation_required, permission_denied, process_gone, audit_log_failure.

- [ ] Step 1: Write failing policy tests.

Use real short-lived child processes. Test missing fingerprint rejection, PID/creation-time mismatch rejection, manager-PID rejection, PID 1/kernel-thread protection, system confirmation requirement, graceful SIGTERM, and explicit SIGKILL when force=true. Assert an audit JSONL record is written for both accepted and rejected attempts.

- [ ] Step 2: Run the action tests.

Run: python3 -m unittest -v tests.test_actions
Expected: FAIL because process_manager.actions does not exist.

- [ ] Step 3: Implement minimum guarded signaling.

Re-read the target with psutil.Process, compare creation time within a small fixed tolerance, classify it again, reject protected/system-unconfirmed targets, send only to the target PID (not its process group), and append one JSON object per attempt. Use terminate() for normal stop and kill() only for explicit force.

- [ ] Step 4: Run the action tests.

Run: python3 -m unittest -v tests.test_actions
Expected: PASS with child processes cleaned up in test teardown.

### Task 4: Add authenticated HTTP API and browser UI

**Files:**
- Create: process_manager/server.py.
- Create: process_manager/static/index.html.
- Create: process_manager/run.py.
- Create: tests/test_server.py.

**Interfaces:**
- GET /healthz -> 200 {"ok": true} without auth.
- GET /api/processes -> authenticated 200 {"generated_at": ..., "processes": [...]}.
- POST /api/processes/<pid>/stop -> authenticated JSON request/response using StopRequest.
- GET / -> browser UI with columns for CLASS, REASON, PID, USER, CPU, RAM, GPU MEM, COMMAND, and action buttons.
- run.py accepts --host, --port, --token, and --audit-log; it refuses missing tokens and wildcard host values.

- [ ] Step 1: Write failing HTTP tests.

Start the real server on an ephemeral loopback port with a test token. Assert health works without auth, process data rejects missing/wrong auth, valid auth returns SYSTEM/USER fields, and stop rejects a request without a creation-time fingerprint.

- [ ] Step 2: Run the server tests.

Run: python3 -m unittest -v tests.test_server
Expected: FAIL because process_manager.server does not exist.

- [ ] Step 3: Implement the API and static UI.

Use ThreadingHTTPServer and a bounded request body. Return JSON errors with stable codes, set Cache-Control: no-store, avoid wildcard CORS, and escape command text in the UI. The UI must show a red SYSTEM badge and reason text, a neutral USER badge, confirmation dialogs for system/force actions, and refresh only after the previous request completes.

- [ ] Step 4: Run server tests.

Run: python3 -m unittest -v tests.test_server
Expected: PASS.

### Task 5: Add dependency, service example, documentation, and end-to-end verification

**Files:**
- Create: requirements.txt.
- Create: process_manager/nv-process-manager.service.example.
- Modify: README.md.
- Modify: Makefile only if a test target is needed; preserve existing C targets.
- Create: tests/__init__.py.

**Interfaces:**
- requirements.txt pins psutil>=5.9,<6.
- The example systemd unit runs a root-owned runtime copy outside the user's home with a root-only token file, waits for an explicit Tailscale IP, restarts on failure, writes audit logs outside Git, and is enabled explicitly with systemctl.

- [ ] Step 1: Write service and usage documentation.

Document local-only startup, Tailscale startup using --host 100.108.68.20 --port 9001, token setup without putting secrets in command-line history, system labels, protected process behavior, and the fact that listing all processes does not mean PID 1/kernel threads are killable.

- [ ] Step 2: Run the full Python test suite.

Run: python3 -m unittest discover -v
Expected: all tests pass with zero failures and zero errors.

- [ ] Step 3: Run repository C regression tests.

Run: make test
Expected: existing test_meminfo passes.

- [ ] Step 4: Run syntax and diff checks.

Run: python3 -m compileall -q process_manager tests and git diff --check
Expected: both commands exit 0.

- [ ] Step 5: Commit the feature on the feature branch.

Run: git add process_manager tests requirements.txt README.md process_manager/nv-process-manager.service.example and git commit -m "feat: add guarded process manager on port 9001"
Expected: only the process manager feature files are committed.

- [ ] Step 6: Push the feature branch.

Run: git push -u origin codex/process-manager-9001
Expected: the branch is published without changing main.

## Verification Summary

The feature is complete only when the full Python suite, existing C unit test, compile check, and diff check pass; the UI labels system rows with reasons; unauthenticated API access is rejected; protected processes cannot be signaled; the boot unit waits for Tailscale and restarts on failure; and the feature branch contains no credentials or runtime evidence.

# Project Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every approved project-audit improvement except the explicitly excluded data-protection scope, while preserving existing files, DBs, CLI, and Windows deployment behavior.

**Architecture:** Deliver four risk-ordered batches: revisioned save consistency, resource-bounded loading and input policy, sequence-aware capture recovery and recovery UX, then signed user-approved updates with rollback. Additive metadata and DB migrations preserve legacy inputs; facade APIs remain stable.

**Tech Stack:** Python 3.10+, PyQt6, Selenium, SQLite3, pytest, pyright, PyInstaller, `cryptography` for Ed25519 release-manifest verification.

## Global Constraints

- Preserve backward reads for existing JSON sessions, runtime manifests/segments, SQLite DBs, settings, presets, and URL history.
- Keep Windows as the supported desktop platform and retain portable/frozen/development storage modes.
- Keep `MainWindow`, compatibility shims, and existing CLI smoke options stable.
- Use additive SQLite migrations only.
- Exclude encryption, key management for user data, retention-period controls, and local-data purge features.
- Implement behavior changes test-first and keep full pytest, pyright, source smoke, and constructor smoke green.

---

### Task 1: Revisioned Session Dirty State

**Files:**
- Modify: `ui/main_window_impl/runtime_state.py`
- Modify: `ui/main_window_impl/runtime_driver.py`
- Modify: `ui/main_window_types.py`
- Test: `tests/test_session_revision.py`

**Interfaces:**
- Produces: `_get_session_revision() -> int`, `_mark_session_dirty() -> int`, `_clear_session_dirty(saved_revision: int | None = None) -> bool`, `_reset_session_revision(*, dirty: bool = False) -> None`.
- Preserves: `_has_dirty_session() -> bool` and `_session_dirty` compatibility.

- [ ] **Step 1: Write failing revision-state tests**

```python
def test_clear_only_succeeds_for_current_revision():
    win = build_window()
    saved = win._mark_session_dirty()
    win._mark_session_dirty()
    assert win._clear_session_dirty(saved_revision=saved) is False
    assert win._has_dirty_session() is True
```

- [ ] **Step 2: Run `pytest tests/test_session_revision.py -q` and confirm failure**
- [ ] **Step 3: Implement monotonic revision/baseline state and compatibility boolean synchronization**
- [ ] **Step 4: Route existing reset/load/new-run clean transitions through `_reset_session_revision()`**
- [ ] **Step 5: Run revision tests plus `tests/test_lossless_session_plan_20260401.py`**
- [ ] **Step 6: Commit `fix: make session dirty state revision-aware`**

### Task 2: Snapshot Revision and Deferred-Action Safety

**Files:**
- Modify: `ui/main_window_impl/persistence_session.py`
- Modify: `ui/main_window_impl/pipeline_messages.py`
- Test: `tests/test_session_revision.py`

**Interfaces:**
- Consumes: Task 1 revision methods.
- Produces: `session_save_done` payload fields `operation_id: str` and `snapshot_revision: int`.

- [ ] **Step 1: Add failing tests for append/edit/delete during async save and stale completion**

```python
def test_async_save_completion_does_not_clean_newer_changes():
    win = build_window()
    snapshot_revision = win._mark_session_dirty()
    win._mark_session_dirty()
    win._handle_message("session_save_done", {
        "saved_count": 1,
        "snapshot_revision": snapshot_revision,
        "operation_id": "save-1",
    })
    assert win._has_dirty_session()
```

- [ ] **Step 2: Run the new tests and confirm stale completion currently clears dirty**
- [ ] **Step 3: Capture UUID operation ID and revision before starting the worker**
- [ ] **Step 4: Clear dirty and resume deferred actions only when revisions match**
- [ ] **Step 5: Report “snapshot saved; later changes remain unsaved” for mismatches**
- [ ] **Step 6: Run session, close-event, and persistence regression tests**
- [ ] **Step 7: Commit `fix: preserve post-snapshot session changes`**

### Task 3: Idempotent DB Saves and Final Completion Semantics

**Files:**
- Modify: `core/database_impl/schema.py`
- Modify: `core/database_impl/sessions.py`
- Modify: `ui/main_window_impl/database_worker.py`
- Modify: `ui/main_window_impl/persistence_session.py`
- Test: `tests/test_database_manager.py`
- Test: `tests/test_session_revision.py`

**Interfaces:**
- Produces: `DatabaseManager.save_session()` accepts `save_operation_id`; duplicate operation returns the existing session ID.
- Changes: session snapshot DB wait uses `timeout=None`; generic sync DB tasks retain configurable timeout.

- [ ] **Step 1: Add failing migration and duplicate-operation tests**

```python
def test_save_session_operation_id_is_idempotent(db):
    payload = {"save_operation_id": "op-1", "subtitles": []}
    assert db.save_session(payload) == db.save_session(payload)
    assert len(db.list_sessions()) == 1
```

- [ ] **Step 2: Add a failing late-completion test proving timeout cannot be reported as final failure**
- [ ] **Step 3: Add nullable `save_operation_id` column and unique partial index**
- [ ] **Step 4: Lookup existing operation before insert and handle uniqueness races inside the DB lock**
- [ ] **Step 5: Pass the save operation through persistence and wait for actual DB completion**
- [ ] **Step 6: Run DB/session tests and migration against a legacy fixture**
- [ ] **Step 7: Commit `fix: make session database saves idempotent`**

### Task 4: Shared Resource Budget

**Files:**
- Create: `core/resource_budget.py`
- Modify: `core/config.py`
- Test: `tests/test_resource_budget.py`

**Interfaces:**
- Produces: `ResourceBudgetLimits`, `ResourceBudget`, `ResourceLimitExceeded`, `check_file_size(path, *, per_file_limit, label)`.

- [ ] **Step 1: Write failing unit tests for per-file, cumulative-byte, entry, segment, and cancel limits**
- [ ] **Step 2: Run `pytest tests/test_resource_budget.py -q` and confirm missing API failure**
- [ ] **Step 3: Implement immutable limits and thread-safe budget counters**

```python
@dataclass(frozen=True)
class ResourceBudgetLimits:
    per_file_bytes: int
    total_bytes: int
    max_entries: int
    max_segments: int
```

- [ ] **Step 4: Add explicit config values derived from the existing 100MB session limit and 150,000 hydrate limit**
- [ ] **Step 5: Run unit tests and pyright for the new module**
- [ ] **Step 6: Commit `feat: add shared session resource budgets`**

### Task 5: Resource-Bounded JSON and Runtime Recovery

**Files:**
- Modify: `ui/main_window_impl/persistence_session.py`
- Modify: `ui/main_window_impl/persistence_runtime_manifest.py`
- Modify: `ui/main_window_impl/persistence_runtime_segments.py`
- Modify: `ui/main_window_impl/persistence_runtime_hydration.py`
- Test: `tests/test_runtime_resource_limits.py`

**Interfaces:**
- Consumes: Task 4 budget API.
- Produces: load payload resource summary and typed resource-limit failure messages.

- [ ] **Step 1: Add failing tests for a small manifest referencing an oversized segment and cumulative segment overflow**
- [ ] **Step 2: Add failing salvage tests for segment-count and entry-count limits**
- [ ] **Step 3: Check every manifest/segment/tail file before `json.load()`**
- [ ] **Step 4: Share one budget across strict load, salvage, and hydration**
- [ ] **Step 5: Preserve path traversal and fingerprint checks, and classify budget errors separately from corruption**
- [ ] **Step 6: Run runtime archive, salvage, recovery, and new resource-limit tests**
- [ ] **Step 7: Commit `fix: bound runtime session recovery resources`**

### Task 6: Incremental and Cancelable DB Session Loading

**Files:**
- Modify: `core/database_impl/sessions.py`
- Modify: `ui/main_window_impl/database_worker.py`
- Modify: `ui/main_window_impl/database_dialogs.py`
- Modify: `ui/main_window_impl/pipeline_messages.py`
- Test: `tests/test_database_stream_load.py`

**Interfaces:**
- Produces: `get_session_metadata(session_id)`, `iter_session_subtitles(session_id, *, batch_size=500)`, and progress control messages.
- Consumes: Task 4 budget and existing request-token stale-drop behavior.

- [ ] **Step 1: Write failing tests proving `fetchall()` is not used for subtitle rows**
- [ ] **Step 2: Write failing cancel and over-limit tests that preserve the current session**
- [ ] **Step 3: Implement metadata lookup and `fetchmany()` iterator with connection-lock ownership**
- [ ] **Step 4: Build entries in the DB worker with batch progress and cancel checks**
- [ ] **Step 5: Swap the current session only after complete success**
- [ ] **Step 6: Run DB load, dialog, long-session, and shutdown tests**
- [ ] **Step 7: Commit `feat: stream large database session loads`**

### Task 7: Windows Canonical Save Paths

**Files:**
- Modify: `core/file_io.py`
- Modify: `ui/main_window_impl/persistence_exports.py`
- Test: `tests/test_export_hardening.py`

**Interfaces:**
- Produces: `canonical_path_key(path: str | Path) -> str`.

- [ ] **Step 1: Add failing drive/path/extension case-alias tests with Windows-specific assertions**
- [ ] **Step 2: Implement `normcase(realpath(abspath(path)))` key generation**
- [ ] **Step 3: Use the helper for active-save registration and cleanup**
- [ ] **Step 4: Run export, atomic-write, and path tests**
- [ ] **Step 5: Commit `fix: canonicalize concurrent save targets on Windows`**

### Task 8: URL, Preset, History, and Network Payload Limits

**Files:**
- Modify: `core/url_policy.py`
- Modify: `core/live_list.py`
- Modify: `core/config.py`
- Modify: `ui/main_window_impl/ui/history_presets.py`
- Modify: `ui/main_window_impl/capture_live.py`
- Modify: `ui/dialogs.py`
- Test: `tests/test_url_policy.py`
- Test: `tests/test_input_resource_limits.py`

**Interfaces:**
- Produces: normalized player/press-player URLs, `read_limited_json_file()`, and bounded live-list parsing.

- [ ] **Step 1: Add failing tests for invalid path, port, query casing/token, URL length, and string limits**
- [ ] **Step 2: Add failing oversized preset/history/live-list tests**
- [ ] **Step 3: Normalize accepted URL paths and query tokens while preserving valid legacy URLs**
- [ ] **Step 4: Quarantine invalid legacy items in memory and warn without rewriting the source file**
- [ ] **Step 5: Read network/file payloads with hard byte limits before JSON parsing**
- [ ] **Step 6: Run URL, live-list, preset, storage preflight, and dialog tests**
- [ ] **Step 7: Commit `fix: validate capture inputs and payload sizes`**

### Task 9: Sequence-Aware Preview Gap Recovery

**Files:**
- Modify: `ui/main_window_common.py`
- Modify: `ui/main_window_impl/runtime_state.py`
- Modify: `ui/main_window_impl/pipeline_queue.py`
- Modify: `ui/main_window_impl/pipeline_messages.py`
- Modify: `ui/main_window_impl/capture_browser.py`
- Test: `tests/test_preview_gap_recovery.py`

**Interfaces:**
- Produces: optional `sequence` on `WorkerQueueMessage`, `capture_resync_request` command, and `capture_full_snapshot` response.
- Preserves: legacy tuple and sequence-less worker messages.

- [ ] **Step 1: Add failing tests for ordered, duplicate, stale-run, and skipped sequences**
- [ ] **Step 2: Add failing queue-overflow test requiring a full snapshot before further append**
- [ ] **Step 3: Allocate sequence numbers per capture run in the worker envelope**
- [ ] **Step 4: Detect gaps in UI and suppress incremental preview until full snapshot arrives**
- [ ] **Step 5: Add a thread-safe UI-to-worker resync event and structured snapshot response**
- [ ] **Step 6: Rebuild suffix/history and resume sequence tracking after snapshot**
- [ ] **Step 7: Run queue, worker, reconnect, pipeline, and fuzz regressions**
- [ ] **Step 8: Commit `fix: recover capture state after preview queue gaps`**

### Task 10: Capture Quality Metadata

**Files:**
- Modify: `core/models.py`
- Modify: `core/database_impl/schema.py`
- Modify: `core/database_impl/sessions.py`
- Modify: `ui/main_window_impl/pipeline_queue.py`
- Modify: `ui/main_window_impl/persistence_session.py`
- Test: `tests/test_capture_quality.py`

**Interfaces:**
- Produces: backward-compatible `capture_quality` mapping with drop/gap/reconnect/desync/salvage counters.

- [ ] **Step 1: Add failing JSON and DB round-trip tests for optional quality metadata**
- [ ] **Step 2: Add failing counter tests for queue drop, gap, reconnect, desync, and salvage**
- [ ] **Step 3: Add a focused quality-state dataclass with serialization helpers**
- [ ] **Step 4: Persist quality JSON and an additive DB JSON column**
- [ ] **Step 5: Show a concise quality summary after stop/save/load**
- [ ] **Step 6: Run model, session, DB, and queue tests**
- [ ] **Step 7: Commit `feat: persist capture quality diagnostics`**

### Task 11: Recovery Candidate Selection

**Files:**
- Create: `core/recovery_candidates.py`
- Modify: `ui/main_window_impl/persistence_session.py`
- Modify: `ui/dialogs.py`
- Test: `tests/test_recovery_candidates.py`

**Interfaces:**
- Produces: `RecoveryCandidate`, `discover_recovery_candidates()`, and `RecoveryCandidateDialog`.

- [ ] **Step 1: Add failing discovery/order/integrity tests for runtime, tail, and backup candidates**
- [ ] **Step 2: Implement metadata-only candidate inspection under resource budgets**
- [ ] **Step 3: Build a dialog showing time, entry count, source, integrity, and warnings**
- [ ] **Step 4: Replace the yes/no startup prompt with candidate selection while retaining single-candidate compatibility**
- [ ] **Step 5: Keep current session unchanged on cancel/load failure and include salvage/quality in completion summary**
- [ ] **Step 6: Run recovery, dialogs, session resilience, and constructor smoke tests**
- [ ] **Step 7: Commit `feat: add recovery candidate selection`**

### Task 12: Signed Release Manifest Verification

**Files:**
- Create: `core/update_manifest.py`
- Modify: `core/config.py`
- Modify: `requirements-dev.txt`
- Modify: `subtitle_extractor.spec`
- Test: `tests/test_update_manifest.py`

**Interfaces:**
- Produces: `ReleaseManifest`, `verify_release_manifest()`, `is_newer_version()`, and bounded manifest download.

- [ ] **Step 1: Add failing Ed25519 valid/tampered/wrong-key/version tests using an in-test keypair**
- [ ] **Step 2: Pin `cryptography` and include its runtime modules in the frozen build**
- [ ] **Step 3: Implement canonical JSON signing input and embedded-public-key verification**
- [ ] **Step 4: Reject unsigned, oversized, expired, downgrade, and hash-invalid manifests**
- [ ] **Step 5: Run update tests, dependency import smoke, and pyright**
- [ ] **Step 6: Commit `feat: verify signed release manifests`**

### Task 13: User-Approved Update, Smoke, and Rollback

**Files:**
- Create: `core/update_installer.py`
- Create: `scripts/apply_update.py`
- Modify: `국회의사중계 자막.py`
- Modify: `ui/main_window_impl/ui/menus.py`
- Modify: `ui/main_window_impl/runtime_lifecycle.py`
- Modify: `subtitle_extractor.spec`
- Test: `tests/test_update_installer.py`

**Interfaces:**
- Produces: staged download, explicit approval, backup, replacement, smoke validation, rollback, and portable-mode path policy.

- [ ] **Step 1: Add failing tests for user cancel, hash mismatch, successful staged replacement, smoke failure rollback, and portable mode**
- [ ] **Step 2: Implement bounded streaming download to a staging directory under storage root**
- [ ] **Step 3: Verify manifest signature and artifact hash before presenting install approval**
- [ ] **Step 4: Implement helper-process replacement with explicit target/backup/staged path validation**
- [ ] **Step 5: Run the new executable with `--smoke`; restore backup on nonzero exit**
- [ ] **Step 6: Add Check for Updates UI and prohibit installation in unsigned development configuration**
- [ ] **Step 7: Add Authenticode hook inputs without embedding certificate secrets**
- [ ] **Step 8: Run updater tests, constructor smoke, and frozen fixture smoke**
- [ ] **Step 9: Commit `feat: add approved updates with rollback`**

### Task 14: Documentation, CI, and Release Gates

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `PROJECT_AUDIT.md`
- Modify: `docs/RELEASE_CHECKLIST.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/run_release_verification.py`
- Test: `tests/test_ci_workflow.py`
- Test: `tests/test_release_verification.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented operation contracts and automated release gates.

- [ ] **Step 1: Add failing CI/release tests for update fixture verification and rollback smoke**
- [ ] **Step 2: Update release verification to run resource, update-signature, and rollback fixture checks**
- [ ] **Step 3: Document revisioned save, large-load UX, URL policy, quality metadata, recovery selection, and updates**
- [ ] **Step 4: Mark resolved audit items with exact code/test evidence and retain residual external-certificate limitations**
- [ ] **Step 5: Run `git diff --check`, encoding hygiene, CI workflow tests, and release-verifier tests**
- [ ] **Step 6: Commit `docs: document audit remediation and release gates`**

### Task 15: Full Verification and Main Publication

**Files:**
- Verify: entire repository

**Interfaces:**
- Consumes: Tasks 1-14.
- Produces: a verified main branch with no uncommitted implementation changes.

- [ ] **Step 1: Run `pytest -q` and require zero failures**
- [ ] **Step 2: Run `python scripts/check_before_push.py --pyright-only` and require zero errors/warnings**
- [ ] **Step 3: Run source smoke and `--smoke-instantiate-window` with isolated storage**
- [ ] **Step 4: Run `python scripts/run_release_verification.py --offline --skip-build --instantiate-window`**
- [ ] **Step 5: Run `git diff --check` and inspect `git status --short`**
- [ ] **Step 6: Push the verified commits to `main`**

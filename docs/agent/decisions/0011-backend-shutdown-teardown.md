# 0011: Backend shutdown performs LLM teardown first

- Status: Accepted
- Date: 2026-10-27
- Context: The "Shut Down Backend" button (App.tsx → main.py) SIGINTed the FastAPI
  process immediately, leaving the active framework's model resident in RAM and its
  server running. Decision 0005 already defines the correct teardown sequence
  (unload, then stop server) but only reached it via the framework-switch path.
- Decision:
  1. Shutdown = teardown (unload active model → stop active LLM server) then kill.
  2. Two requests, not one: `GET /api/shutdown/teardown/stream` streams the teardown
     to completion while the backend is still alive; on `[SUCCESS]` the frontend fires
     the existing `POST /api/shutdown` unchanged. Nothing self-kills mid-stream.
  3. One pre-flight confirm only; the sequence then runs to the kill without asking.
  4. Active run: warn in the confirm and proceed. Deliberately NOT 0005's hard refusal.
  5. The kill endpoint calls `mark_active_run_interrupted()`, setting the in-flight run
     to the existing "failed" status, so no row is left at "running" forever.
  6. Teardown touches the active framework only.
  7. Teardown failures emit `[WARNING]` lines, never `[ERROR]`; the kill proceeds.
  8. `FrameworkManager.stream_teardown(framework)` is the single implementation;
     `stream_switch_framework` consumes it with `yield from` and owns step numbering
     (its steps became 1/3..3/3 as its first two steps merged into the teardown).
  9. New `ShutdownTerminal.tsx`; on completion it clears the 5s status poll and
     disables the controls that would hit the dead port.
- Alternatives considered:
  - Self-kill on a `threading.Timer` after flushing `[SUCCESS]` mid-stream: rejected;
    required ordering the signal against the response flush. The two-request split
    removes the race instead of timing around it.
  - Blocking POST with synchronous teardown: rejected; ~30s of silent UI (two 15s
    subprocess timeouts plus a settle).
  - Refuse shutdown while a run is active, as `/api/framework/switch` does: rejected.
    Shutdown is the escape hatch for a hung run; refusing forces ctrl-C, which skips
    teardown entirely and so defeats this decision.
  - A second confirmation after teardown, with a "Keep Backend Running" cancel path:
    rejected; no use case for cancelling, and a one-button dialog is only a nag.
  - `window.confirm()` layered over the terminal modal: rejected; hides the log the
    decision depends on.
  - Failing all "running" rows in `on_startup` instead of at kill time: rejected as the
    primary mechanism; fires every boot and cannot tell a crash from an intentional
    kill. Still wanted as a complement for crash paths — see T-017.
  - Tearing down both frameworks: rejected; the inactive one may be running for
    something other than this app.
  - Generalising `ModelLoadTerminal`: rejected; its `isProgressLine` collapsing is
    useless here and its `onFinished` contract (refetch models) is wrong.
- Consequences: T-016. Teardown logic has one home, so 0005's switch path and the
  shutdown path cannot drift. Shutdown is now slow (seconds) and must show progress.
- Revisit if: a third caller needs teardown, or a framework gains a single
  stop-and-unload primitive making the two steps one.

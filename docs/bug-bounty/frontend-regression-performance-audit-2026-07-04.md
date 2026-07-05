# Frontend Bug Bounty: Regression and Performance Audit

Date: 2026-07-04
Scope: `frontend/src` static review, focused on likely regressions, correctness risks, security-adjacent issues, and performance improvements.

## Executive Summary

The frontend is in solid shape overall: API access is mostly centralized, high-risk guide HTML sinks route through sanitization, many utility and workflow paths have tests, and the Library has already had meaningful performance work through memoized cards and React Query.

The best findings are in edge-case correctness and cleanup discipline:

- Guide custom CSS is sanitized for dangerous tokens but still injected globally.
- Import collection assignment can silently fail.
- Long-running polling and timers can update after component unmount.
- Download helpers revoke blob URLs immediately after triggering downloads.

The main performance risks are not urgent today, but they will matter with larger libraries: per-card gallery timers, full tag-list filtering on every render, and expensive 3D viewer settings.

## Findings

### P1: Guide `head_style` CSS is injected globally

Severity: High
Confidence: High
Category: Security-adjacent / UI integrity

Evidence:

- `frontend/src/components/guide/GuideReader.tsx:292`
- `frontend/src/components/guide/GuideReader.tsx:293`
- `frontend/src/components/guide/GuideReader.tsx:299`
- `frontend/src/lib/sanitizeHtml.ts:46`

Guide HTML bodies are sanitized well before `dangerouslySetInnerHTML`, but `guide.head_style` is injected into a `<style>` tag after only token-level CSS sanitization. The code replaces `:root` with `.guide-reader`, but other selectors remain global.

Examples that can still affect the whole SPA:

```css
body { display: none; }
button { pointer-events: none; }
.fixed { z-index: -1; }
* { cursor: none; }
```

This is not script execution, but it is still a stored UI-integrity issue if guide content is imported or generated from untrusted input.

Impact:

- A malformed or malicious guide can break navigation, modals, buttons, or page layout outside the guide reader.
- The failure mode can look like a general app bug rather than guide-specific content.

Recommendation:

Scope custom guide CSS structurally before injection. Good options:

- Parse rules and prefix selectors with `.guide-reader`.
- Allow only CSS custom properties and a small set of known selectors.
- Store guide theme data as structured JSON rather than accepting arbitrary CSS where possible.

Suggested tests:

- `body { display:none }` in `head_style` does not affect `document.body`.
- `.guide-reader .step { ... }` still applies inside the guide.
- Dangerous URL/import/expression cases remain blocked.

### P1: Import collection assignment can silently fail

Severity: High
Confidence: High
Category: Correctness / data loss perception

Evidence:

- `frontend/src/api/collections.ts:32`
- `frontend/src/api/collections.ts:33`
- `frontend/src/pages/ImportPreviewPage.tsx:258`

`collectionsApi.bulkAddModels()` fires a `fetch()` for each model and awaits `Promise.all`, but it never checks `res.ok`. HTTP 4xx/5xx responses resolve successfully, so callers proceed as if collection assignment worked.

Import preview uses this during pack import after scan/enrich/tag writes. The user can get a successful import toast while selected collection links were not actually created.

Impact:

- Imported models may be missing from collections the user explicitly selected.
- Failures are hidden, so users do not know to retry.
- Partial collection assignment can leave a pack inconsistently organized.

Recommendation:

Make `bulkAddModels()` validate every response and throw on any non-2xx. Prefer returning a count or result summary so the import page can report partial failures cleanly.

Suggested tests:

- One failed add response makes `bulkAddModels()` reject.
- Import preview shows an error when collection assignment fails.
- All successful adds preserve current import success behavior.

### P2: Refresh metadata polling can update after unmount

Severity: Medium
Confidence: High
Category: Correctness / lifecycle

Evidence:

- `frontend/src/components/RefreshEnrich.tsx:22`
- `frontend/src/components/RefreshEnrich.tsx:28`
- `frontend/src/components/RefreshEnrich.tsx:84`
- `frontend/src/components/RefreshEnrich.tsx:100`

`pollUntilDone()` loops until the backend refresh finishes. The component awaits it inside `run()`, then calls `toast()`, `onDone()`, and `setRunning(false)`. If the user navigates away during a long refresh, the promise continues and later updates component state.

Impact:

- React may warn about state updates after unmount.
- `onDone()` can invalidate or update a parent that no longer exists.
- Long refresh jobs have no frontend cancellation path.

Recommendation:

Use an `AbortController` or mounted ref. Stop polling on unmount and skip local state updates once the component is gone. If the backend refresh continues, surface status through a shared query/poller instead of a component-local loop.

Suggested tests:

- Unmount during polling does not call `setRunning`.
- Unmount during polling does not call `onDone`.
- Active component still reports completion normally.

### P2: Toast timers are not tracked or cleared

Severity: Medium
Confidence: Medium
Category: Lifecycle / test stability

Evidence:

- `frontend/src/context/ToastContext.tsx:20`
- `frontend/src/context/ToastContext.tsx:27`
- `frontend/src/context/ToastContext.tsx:31`

Each toast schedules a `setTimeout()` to remove itself, but the timer IDs are not stored and no provider cleanup clears pending timers. In the normal SPA lifetime this is low-risk because the provider rarely unmounts. In restore/reset reload flows, tests, or future provider remounts, pending callbacks can fire after unmount.

Impact:

- Potential state updates after unmount.
- Test flakiness with fake timers or provider remounts.
- Timer buildup during bursty error paths.

Recommendation:

Track timeout IDs in a ref and clear them in a provider cleanup effect. Also clear the matching timer when a toast is manually dismissed.

Suggested tests:

- Provider unmount clears pending toast timers.
- Manual dismiss prevents the auto-dismiss callback from firing later.

### P2: Blob download URLs are revoked immediately after click

Severity: Medium
Confidence: Medium
Category: Browser compatibility / downloads

Evidence:

- `frontend/src/api/base.ts:69`
- `frontend/src/api/base.ts:73`
- `frontend/src/api/base.ts:74`
- `frontend/src/api/files.ts:36`
- `frontend/src/api/files.ts:40`
- `frontend/src/api/files.ts:41`
- `frontend/src/api/database.ts:9`
- `frontend/src/api/database.ts:13`
- `frontend/src/api/database.ts:14`
- `frontend/src/api/painting.ts:71`
- `frontend/src/api/painting.ts:75`
- `frontend/src/api/painting.ts:76`

Several helpers create a blob URL, click a temporary anchor, then revoke the URL synchronously. Some browsers tolerate this; others can cancel or corrupt downloads if the object URL is revoked before the download stack consumes it.

Impact:

- Intermittent failed downloads for backups, ZIPs, CSV exports, or guide PDFs depending on browser/runtime.
- Hard to reproduce because timing varies by engine.

Recommendation:

Centralize browser download behavior in one helper:

- Create object URL.
- Append anchor to `document.body`.
- Click it.
- Remove anchor.
- Revoke URL in a `setTimeout(..., 0)` or after a short delay.

Suggested tests:

- One shared helper is used by backup, ZIP, CSV, and PDF downloads.
- The helper calls `URL.revokeObjectURL` asynchronously.

### P3: Gallery rotator hover timer is not cleared on unmount

Severity: Low
Confidence: High
Category: Lifecycle / cleanup

Evidence:

- `frontend/src/components/ModelCard.tsx:573`
- `frontend/src/components/ModelCard.tsx:595`
- `frontend/src/components/ModelCard.tsx:635`
- `frontend/src/components/ModelCard.tsx:638`

`GalleryRotator` tracks three timers. It clears `fadeTimerRef` on unmount and clears the interval in an effect cleanup, but `labelTimerRef` is only cleared on mouse leave. If a card unmounts while hovered before the four-second label delay completes, the timeout can fire after unmount.

Impact:

- Possible state update after unmount.
- Minor memory/timer leak in rapid navigation or pagination.

Recommendation:

Extend the unmount cleanup to clear `labelTimerRef` as well.

Suggested tests:

- Hover then unmount before four seconds; no state update runs.

### P3: Import preview image rotator leaves fade timeouts untracked

Severity: Low
Confidence: High
Category: Lifecycle / cleanup

Evidence:

- `frontend/src/pages/ImportPreviewPage.tsx:569`
- `frontend/src/pages/ImportPreviewPage.tsx:573`
- `frontend/src/pages/ImportPreviewPage.tsx:581`
- `frontend/src/pages/ImportPreviewPage.tsx:585`
- `frontend/src/pages/ImportPreviewPage.tsx:589`

`ImageRotator` cleans up its interval, but the nested fade `setTimeout()` calls are not stored or cleared. Closing/collapsing a card while a fade is pending can leave a late `setState()`.

Impact:

- Possible state update after unmount.
- Small timer leak during import preview review.

Recommendation:

Store the fade timeout in a ref, clear it before scheduling a new one, and clear it on unmount.

Suggested tests:

- Trigger a fade, unmount, advance timers; no state update occurs.

### P3: 3D viewer attaches WebGL context listener without cleanup

Severity: Low
Confidence: Medium
Category: Lifecycle / WebGL resource hygiene

Evidence:

- `frontend/src/components/STLViewer.tsx:380`
- `frontend/src/components/STLViewer.tsx:387`

The Canvas `onCreated` callback attaches a `webglcontextlost` listener using an inline callback. Because the handler is not named or stored, it cannot be removed on unmount.

Impact:

- Likely low because the canvas element is removed with the listener.
- Still weak cleanup discipline in a component that already deals with scarce WebGL contexts.

Recommendation:

Use a small child component or effect that registers a named listener and removes it in cleanup. Also consider explicitly disposing loader geometry/materials if profiling shows retained GPU resources during rapid model navigation.

Suggested tests:

- Mount/unmount viewer and assert listener cleanup where practical with a mocked canvas.

### P3: Settings load failure silently leaves defaults active

Severity: Low
Confidence: High
Category: Correctness / user feedback

Evidence:

- `frontend/src/context/AppSettingsContext.tsx:64`
- `frontend/src/context/AppSettingsContext.tsx:67`

If `api.settings.get()` fails, the catch block swallows the error and leaves hardcoded defaults active. Those defaults hide or change meaningful app behavior such as painting guides, NSFW visibility, page size, sort, and AI settings.

Impact:

- A transient settings failure can make features disappear without explanation.
- Users may change settings based on stale defaults.
- Troubleshooting is harder because no error is surfaced.

Recommendation:

Track settings load state and error in context. Surface a small banner or toast when settings cannot load, and consider retry. Avoid letting dangerous defaults masquerade as confirmed server settings.

Suggested tests:

- Failed settings load exposes an error state.
- Consumers can distinguish "loading defaults" from "server-confirmed settings."

### P3: Library tag filtering does synchronous full-list work each render

Severity: Low
Confidence: Medium
Category: Performance

Evidence:

- `frontend/src/pages/library/FilterBar.tsx:93`
- `frontend/src/pages/library/FilterBar.tsx:342`

`visibleTags` is recomputed from `allTags` on every render. That is fine for small tag lists, but tag-heavy libraries will re-filter and render every visible tag repeatedly while unrelated filter-bar state changes.

Impact:

- Filter panel typing can get sluggish with large tag lists.
- Rendering all tags can become more expensive than the filter itself.

Recommendation:

Memoize `visibleTags` by `[allTags, tagSearch]`. If tag counts grow into the thousands, cap visible results or virtualize the tag list.

Suggested tests:

- Tag search output remains unchanged.
- Memoization avoids recomputation when unrelated props change.

## Positive Controls Observed

- `frontend/src/lib/sanitizeHtml.ts` and `frontend/src/components/guide/GuideReader.tsx` sanitize guide HTML at render time.
- API query parameters generally use `URLSearchParams` or `encodeURIComponent`.
- React Query centralizes most server-state fetching and stale-response handling.
- `ModelCard` is memoized to reduce grid churn during selection and keyboard focus.
- Many risky flows have tests: settings, guide reader/editor, import preview, image picker, query hooks, model detail, and library interactions.
- File/image/STL URLs are generated through API helpers rather than hand-built throughout most call sites.

## Suggested Triage Order

1. Scope or restrict guide `head_style` CSS.
2. Fix `bulkAddModels()` to throw on failed collection assignments.
3. Add cancellation/cleanup to `RefreshEnrich` polling.
4. Centralize blob-download behavior and revoke object URLs asynchronously.
5. Sweep timer cleanups in `ToastContext`, `GalleryRotator`, and import preview `ImageRotator`.
6. Add settings-load error state.
7. Memoize or cap tag filtering once tag counts justify it.


# V1.3 Final Acceptance Notes

Date: 2026-10-15

- User-confirmed collection-record default: leave both dates blank and show all historical batches. Keep the existing server-side ordering and 20-row page size. Clearing filters restores all dates, triggers, and anomalies. The frozen Spec's recent-30-day initial date is superseded only for this UI default; date validation, one-sided ranges, automatic queries, page reset, cancellation, and stale-response rejection remain unchanged.
- The simulated five-link add fixture has batch timestamps `2026-10-15T03:45:47.168528` and `2026-10-15T03:45:47.408197`, a real elapsed duration of 0.239669 seconds. The backend duration helper preserves fractional seconds; the UI floors display to whole seconds, so the batch correctly displays `0秒`. Three confirmed page visits describe access count and do not determine elapsed time. No duration business-code change is needed.
- Reused prior evidence in the local ignored `.artifacts/v1.3/implementation-report.md`: Backend 545 passed, Frontend 209 passed, Playwright 57 passed / 1 skipped, V1.3/migration 28 passed, final affected Backend 85 passed, TypeScript/build passed, isolated SQLite upgrade/downgrade integrity checks passed, and Standards / Spec Final Gate P0/P1/P2 = 0/0/0. The report and all generated artifacts stay out of the commit; this note records only the final acceptance delta.

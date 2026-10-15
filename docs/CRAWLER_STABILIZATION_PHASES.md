# Authenticated extraction and seven-day archive

## Native architecture

One installed Chrome/Edge session owns Playwright transport. No browser download,
no anonymous fallback. Native POST pagination preserves the complete original
search template and continuation data. Empty SSR is not source exhaustion;
client-rendered native responses are supported. Detail failures stop the run
rather than approving a listing whose agency evidence could not be checked.
SearchRun persists each listing and remaining candidates for restart recovery.
AccessibleListing is the authoritative publication-time archive for the assistant.
Unknown publication times and CRM insertion dates cannot establish freshness.

## Reference decisions

- ErfanNahidi/Divar_Property_Scraper: separate discovery from detail extraction;
  do not vendor an entire Selenium scraper or share browser objects across threads.
- 2077DevWave/divar_scraper: modular normalization; do not adopt external Workers.
- divar-scraper: session-aware transport; do not expose contact credentials.
- DivarApi: reference only, not a replacement production dependency.
- Apify hipersoft/divar-scraper: API contract reference only; no paid/external runtime.
- pydivar: cursor/filter contracts and bounded detail work. Existing pydivar-style
  pipeline has per-thread HTTP sessions, but is NOT the authenticated watch path.

## Worker

    python -m crawler.authenticated_watch

Runs rent/sale apartment discovery in Tehran, periodic head refresh, resumable
168-hour snapshot backfill, and daily renewal of completed snapshots. A process
file lock prevents duplicate workers. Persistent state is in the ignored
instance/authenticated-watch.json; detailed cursors remain in SearchRun.
Failures are explicit with bounded backoff. The interval is a pause BETWEEN
cycles, not a guaranteed publication-to-ingestion latency. Windows reboot
restart and unattended service installation are not configured.

## Verified and incomplete

34 focused tests pass, including protected-account rejection, current sAccessToken
recognition, publication-window gating, lock/restart state, filter-preserving
pagination and nullable DOM metadata. The public csid cookie remains rejected.

Following manual login, a protected native account response was validated, then
real discovery returned 26/24/24 disjoint records for rent and sale (148 total).
The successful transport in that run was local storage_state using installed
Chrome/Edge, not an assumed CDP attachment. SSR isLoggedIn=false is not reliable
before client hydration; protected-account validation supersedes that check.
A rendered real detail returned area 118, rooms 2 and five CDN images. A real
assistant refresh returned partial coverage and 20 archive listings with links.
The worker subsequently completed a successful cycle and resumed both snapshots.

The seven-day snapshot remains incomplete; no exhaustive Tehran coverage or
100 percent owner verification is claimed. Current worker scope is apartments,
not all residential property classes. Contact retrieval is not established.
Existing records are preserved; older likely-owner classifications are not
retroactively claimed verified. The assistant labels archive results and reports
live-refresh failure/partial status instead of implying exhaustive live coverage.

## Validation

### 2026-10-09 transport follow-up

Authenticated requests now fetches native detail JSON after validating the
protected account endpoint. Browser search bootstrap still preserves Divar's
own filter/pagination template; this is not a fully browser-free pipeline.
Real details for three posts succeeded, including a previously failing post.
The assistant returned 17 archive matches for a 70–100 m² rent query (24 hours),
explicitly marked non-live. Subsequent full cycles received HTTP 429 from Divar.
Detail calls now have a two-second minimum interval, bounded network-only
retries, and a persisted five-minute worker cooldown on rate limiting.
No complete seven-day coverage or permanently healthy monitor is claimed.

### Subsequent measured results

HTTP continuation preserved the original 70–100 m² personal rent filters:
26 first-page and 24 second-page records, zero overlapping tokens. Two real
85 m² posts returned full descriptions (316/363 characters) and 8/1 CDN images;
cached detail responses are labelled and cache copies cannot mutate originals.
The revised full watch cycle succeeded, reaching rent page 21 and sale page 8
(still incomplete). Account metadata rejects agencies before detail requests.
The shared OwnerFilter now gates both crawler and assistant; old likely-owner
labels cannot override it, and substring false positives such as آشپزخانه are
removed. Of 435 archive records inspected, 25 passed the text owner guard;
this is not independent ownership/contact verification. After publication and
financial constraints, the assistant's actual seven-day query returned one
rent and one sale result, not a fabricated 20–30-result batch. Live assistant
refresh was partial/time-budget-limited. SSR detail probes sometimes returned
an empty 200 shell, so SSR alone is not declared a stable full-detail transport.
Two consecutive complete worker cycles subsequently succeeded. Semantic model
calls are now skipped when the mandatory owner guard already rejects a listing;
otherwise those calls consumed crawl budgets without being able to approve it.
Retry-After is honored for rate limiting and survives worker restart. Focused
tests validate these paths; seven-day completion remains a separate condition.
A later cycle exposed a false session failure from waiting for a browser UI
account-response event during checkpoint resume. The HTTP adapter now verifies
the protected account endpoint directly, and resume does not start a browser
just to fetch native details. Browser bootstrap still uses installed Chrome/Edge.

    python -m pytest -q tests/test_divar_listing_dom.py tests/test_authenticated_archive_bridge.py tests/test_authenticated_watch.py tests/test_accessible_divar_search.py tests/test_divar_playwright_session.py tests/test_pydivar_transport.py
    python -m crawler.authenticated_watch --once

No commit, push, deployment, database cleanup, or bot restart was performed.

## Saved policy and phased execution — 2026-10-09

Canonical non-secret policy: `crawler/config/owner_search_policy.json` (version 1).
Scope: Tehran, apartment, personal-account search, 70–100 square metres, separate
rent/sale. Head window: 24 hours; archive window: 168 hours. No district, room,
price or amenity restriction was supplied, so none is fabricated. The shared
OwnerFilter must approve account metadata/title/description; personal-account
metadata alone is not ownership proof. Reject phrases include «فایل شخصی»،
«کلید در اختیار»، «عکس مشابه» and «همکار». No 100-percent ownership or contact
verification is asserted. Only real available matches are returned, up to 30.

The worker uses the policy when creating runs, fingerprints it in health state,
and does not reuse checkpoints with different criteria. Older runs/listings
are preserved, not deleted. Current policy applies to worker collection;
assistant requests still honor their explicitly supplied user filters.

Phases:

1. Save and validate policy; reject weakened authentication/owner rules.
2. Unit/regression validation, including restart, queues, filter preservation.
3. Verify installed Chrome through explicit local CDP and the protected account
   endpoint. Stop visibly if missing/rejected; never use old-state fallback.
4. Search both rent/sale heads; test native continuation and real details/CDN.
5. Resume pending head details, then seven-day backfill with bounded budgets.
   Coverage remains incomplete until source traversal proves completion.
6. Check the real assistant response; disclose archive/partial refresh status.

Local CDP endpoint is in ignored `instance/divar-cdp-runtime.json`; it contains
only the loopback endpoint, no cookies, credentials or personal data. Default
HTTP adapters (including the existing assistant path) honor it. They detach
without closing the user's browser/context/tabs. When that Chrome is closed,
the connection fails explicitly; it does not silently use another session.

Run from the project directory:

    python -m crawler.authenticated_watch --once --policy crawler/config/owner_search_policy.json
    python -m crawler.authenticated_watch --policy crawler/config/owner_search_policy.json --chunk-seconds 60 --head-seconds 30 --interval 120

The interval is between cycles, not a guaranteed instant detection SLA. Source
429/Retry-After cooldown remains mandatory. Reboot service installation is not
part of this change. Earlier measured results above are historical snapshots,
not current live coverage or ownership guarantees.

Measured current policy execution: 129 related tests passed. The selected Chrome
passed protected-account validation; filtered native pages returned 26 and 24
distinct tokens with zero overlap. A real detail returned 85 m², two rooms,
and eight CDN images. Original tab count was preserved after disconnecting.
Rent/sale saved runs contained area 70–100 and a 168-hour archive window.
One bounded full worker cycle succeeded, but coverage remained incomplete.
The real assistant refresh succeeded partially (one page, time budget reached)
and returned two exact rent matches (86/84 m²) plus one explicitly labelled
63 m² nearby suggestion. It labelled results as persisted archive/non-live.
Neither contact access nor independent ownership nor complete seven-day
coverage was verified by these results.

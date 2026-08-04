# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant custom integration (distributed via HACS) for the Romande Énergie
customer portal. It polls daily electricity curves, exposes sensors, and writes
long-term statistics for the Energy dashboard. Everything ships under
`custom_components/romande_energie/`; there is no build step.

## Commands

```bash
pip install -r requirements_test.txt   # pytest + pytest-homeassistant-custom-component
pytest                                 # whole suite (testpaths=tests, asyncio_mode=auto)
pytest tests/test_coordinator_stats.py                       # one file
pytest tests/test_coordinator.py::test_ensure_token_fast_path_skips_refresh   # one test
pytest -k statistic                                          # by name
```

CI (`.github/workflows/`) runs `pytest` on Python 3.13, plus HACS validation and
hassfest on every push/PR. There is no linter configured.

Releasing to HACS means bumping `version` in `custom_components/romande_energie/manifest.json`.

## Architecture

Four modules, layered so the HTTP surface is testable in isolation:

- **`api.py`** — stateless async client (takes an `aiohttp.ClientSession`) plus *pure*
  parsing helpers (`parse_daily_series`, `latest_value`, JWT claim readers). No HA
  imports. All HTTP lives here so `config_flow.py` and `coordinator.py` share one
  implementation. Typed exception hierarchy: `CannotConnect` / `AuthError` /
  `OtpError` / `ApiError`, with `RefreshError` **subclassing `AuthError`** — order
  `except` clauses accordingly.
- **`coordinator.py`** — `DataUpdateCoordinator` owning token lifecycle, the rolling
  curve fetch, statistics ingestion, and the `RomandeEnergieData` snapshot.
- **`config_flow.py`** — multi-step OTP flow; reauth re-enters the same steps.
- **`sensor.py`** — `CoordinatorEntity` sensors driven by a `DESCRIPTIONS` tuple of
  `value_fn` / `day_fn` lambdas over `RomandeEnergieData`.

### Auth model (the reason for most of the tuning constants)

```
login          -> access_token scope=otp_pending   (cannot read data)
send-otp       -> SMS
validate-otp   -> access_token scope=full_access + refresh_token
refresh        -> new access_token + ROTATED refresh_token (no OTP)
```

Access token ~15 min, refresh token ~30 min. `UPDATE_INTERVAL` (20 min) must stay
below **both** TTLs or the session dies and the user must re-enter an SMS code —
do not raise it. Each refresh rotates the refresh token, so
`_persist_refresh_token()` writes it back onto the config entry immediately;
losing that write costs the user an OTP. A `RefreshError` becomes
`ConfigEntryAuthFailed` → HA reauth flow.

Only a *successful* refresh renews the refresh token, so a missed poll is what
actually ends sessions: 20 min + 20 min outlives the 30 min TTL. Two guards keep
the chain alive, and both exist for that arithmetic alone:

- `_refresh_tokens()` retries `CannotConnect`/`ApiError` `REFRESH_ATTEMPTS` times
  inside the same poll (`RefreshError` is *not* retried — the token is already
  dead). A timed-out refresh may have rotated server-side, so the retry can still
  legitimately end in `RefreshError`; that one is unrecoverable.
- `_async_update_data()` drops `update_interval` to `POLL_RETRY_INTERVAL` (3 min)
  after an `UpdateFailed` and restores `UPDATE_INTERVAL` on the next success, so a
  transient outage gets several attempts inside the TTL. The
  `ConfigEntryAuthFailed` path deliberately leaves the interval alone (reauth stops
  the polling anyway).

Note `REFRESH_ENDPOINT` is bare `/v2/refresh/`, not `/login/refresh/` (404).
All endpoint paths use trailing slashes.

### Portal quirks the code deliberately works around

The portal syncs the meter roughly once a day, and publishes the day it is working
on with a partial value (observed ~1/5 of the real total) until a later sync
completes it. Consequences encoded in `coordinator.py`:

- **`_settled()`** drops the newest day when it is today or yesterday, so the daily
  sensors never show a partial figure. Which day that leaves is variable, hence the
  `measurement_day` state attribute — never assume "yesterday".
- **Month totals** are computed by `_calendar_month_total()` over the fetched series,
  *including* the unsettled day. The API's own `curves_statistics.total` is a rolling
  total over the requested window, not month-to-date — don't use it.
- **Statistics re-send the whole window every time it changes**, not just new days.
  External statistics are keyed on `(statistic_id, start)`, so re-sending corrects a
  partial day in place. `self._written` short-circuits an unchanged window to avoid
  ~60 pointless recorder writes an hour (SD-card wear).

### Statistics invariants (break these and the Energy dashboard shows a meter reset)

- The cumulative sum must never go backwards. `_sum_before()` reads the stored sum
  just before the window and returns `None` when history exists but its sum is
  unreadable — the caller then **writes nothing** rather than restarting from zero.
- `_stored_sums()` queries with `period="hour"`. `"day"`/`"week"`/`"month"` realign
  `end_time` forward, pulling the window's own first row into its baseline.
- `_fill_gaps()` inserts `0.0` for missing days: the recorder never deletes rows we
  omit, so a skipped day would keep a stale sum while later days are rewritten.
- Statistic ids are `f"{DOMAIN}:{slugify(contract_id)}_consumption|_surplus"`.
  Contract ids may carry uppercase/hyphens, which are illegal in a statistic id and
  would make every write raise.
- Statistics writing is best-effort: it is wrapped in a broad `except` that only logs,
  so a recorder hiccup cannot blank the sensors.

### Things that are frozen

- Sensor `key`s `consumption_yesterday` / `surplus_yesterday` are misnomers (the
  sensors report the newest *settled* day) but build the entity unique ids. Renaming
  orphans every existing entity and its history.
- Sensors intentionally set **no `state_class`** — external statistics already carry
  the Energy-dashboard history, so a state_class would double-count.

## Testing notes

- `pytest-homeassistant-custom-component` supplies `hass`, `recorder_mock`,
  `enable_custom_integrations`.
- The integration declares `recorder` as a dependency, so **any test that loads a
  config entry or touches statistics must be marked `@pytest.mark.recorder`**.
  `conftest.py`'s `recorder_before_hass` fixture exists purely to order recorder setup
  ahead of `hass`; the autouse fixture depends on it first for that reason.
- Never put real credentials or token blobs in tests. `make_jwt()` in `conftest.py`
  builds unsigned fake JWTs on the fly (the code reads claims, never verifies
  signatures); `build_config_entry()` supplies the fake entry data.
- Coordinator statistics tests stub `get_instance`,
  `statistics_during_period` and `async_add_external_statistics` via monkeypatch on
  the `coordinator` module — see the `stats_env` fixture.

# Integration Quality Scale: where this fork stands

Checked on 2026-11-13 against the 54 rules listed at
https://developers.home-assistant.io/docs/core/integration-quality-scale/rules.
The machine-readable version is `custom_components/nature_remo/quality_scale.yaml`.

**Honest tier today: below Bronze.** Every Bronze rule must be done, and these are still open:
brands, common-modules, docs-actions, docs-removal-instructions, entity-event-setup (audit),
has-entity-name.

Entity unique ids are unchanged on purpose, so the renamed `bottom_reeme_*` entity ids keep working.
The Fujitsu AR-RFF2J encoder and local API code are untouched.

## Bronze (12 done, 6 todo, 2 exempt)

| Rule | Status | Notes |
|---|---|---|
| `action-setup` | done | send_light_mode is registered once in async_setup. |
| `appropriate-polling` | done | 60 s default (2 cloud calls per poll, within Nature's 30 requests / 5 min), user-adjustable in options. |
| `brands` | todo | No logo/icon in home-assistant/brands custom_integrations yet. |
| `common-modules` | todo | coordinator.py exists; a shared entity.py base class does not. |
| `config-flow` | done | UI setup with token check, data_description, token in data and settings in options. |
| `config-flow-test-coverage` | done | tests/test_config_flow.py: success, each error with recovery, duplicates, reauth, reconfigure. |
| `dependency-transparency` | done | Only aiohttp, which Home Assistant ships. |
| `docs-actions` | todo | Document the send_light_mode action in the README. |
| `docs-conditions` | exempt | The integration provides no conditions. |
| `docs-high-level-description` | done | README describes Nature Remo and what the integration controls. |
| `docs-installation-instructions` | done | README has HACS and manual install steps. |
| `docs-removal-instructions` | todo | README needs a removal section. |
| `docs-triggers` | exempt | The integration provides no triggers. |
| `entity-event-setup` | todo | Check every platform subscribes in async_added_to_hass via async_on_remove (climate local poller especially). |
| `entity-unique-id` | done | All entities set unique ids (nature_remo_<platform>_<appliance_id>); unchanged by this branch. |
| `has-entity-name` | todo | Not set yet. Safe for entity ids (they live in the registry) but changes friendly names, so do it deliberately. |
| `runtime-data` | done | entry.runtime_data holds the API client and coordinator; hass.data is no longer used. |
| `test-before-configure` | done | Config flow calls GET /1/users/me before creating the entry. |
| `test-before-setup` | done | Setup checks the token: rejected -> ConfigEntryAuthFailed (reauth), unreachable -> ConfigEntryNotReady. |
| `unique-config-entry` | done | Nature account id is the entry unique id; old entries are matched by token and adopt the id on next setup. |

## Silver (3 done, 7 todo, 0 exempt)

| Rule | Status | Notes |
|---|---|---|
| `action-exceptions` | todo | send_light_mode raises ServiceValidationError for bad input; API failures in entity actions still only log. |
| `config-entry-unloading` | todo | Platforms unload; verify the climate local poller and service are cleaned up on unload. |
| `docs-configuration-parameters` | todo | Document the options (update interval, Remo IPs, local poll, local IR protocol). |
| `docs-installation-parameters` | todo | Document the name and access token fields (strings.json already describes them). |
| `entity-unavailable` | todo | Lock and remote report availability; climate, light and sensor do not yet. |
| `integration-owner` | done | codeowners: @nanosns (upstream), @imasaru (fork). |
| `log-when-unavailable` | todo | Coordinator-based entities get this for free; non-coordinator paths need checking. |
| `parallel-updates` | done | 1 on command platforms, 0 on sensor. |
| `reauthentication-flow` | done | reauth_confirm step, refuses a token from a different account. |
| `test-coverage` | todo | Config flow, setup errors and diagnostics are tested; platforms are not (well under 95%). |

## Gold (3 done, 18 todo, 0 exempt)

| Rule | Status | Notes |
|---|---|---|
| `devices` | done | Entities attach to Remo / appliance devices via device_info. |
| `diagnostics` | done | diagnostics.py, token, serials, MACs, location and Remo IPs redacted. |
| `discovery` | todo | Remo devices are believed to advertise over mDNS (_remo._tcp); confirm on the LAN, then add zeroconf to fill in local IPs. |
| `discovery-update-info` | todo | Depends on discovery; would update a Remo's local IP when it changes. |
| `docs-data-update` | todo |  |
| `docs-examples` | todo |  |
| `docs-known-limitations` | todo | e.g. cloud rate limit, local IR only for Fujitsu AR-RFF2J. |
| `docs-supported-devices` | todo |  |
| `docs-supported-functions` | todo |  |
| `docs-troubleshooting` | todo |  |
| `docs-use-cases` | todo |  |
| `dynamic-devices` | todo | New appliances need a reload today. |
| `entity-category` | todo |  |
| `entity-device-class` | todo | Sensors mostly have device classes; audit the rest. |
| `entity-disabled-by-default` | todo |  |
| `entity-translations` | todo | Needs has-entity-name first. |
| `exception-translations` | todo | Setup and the light action use translated errors; entity actions do not. |
| `icon-translations` | todo | No icons.json yet. |
| `reconfiguration-flow` | done | reconfigure step replaces the token in place. |
| `repair-issues` | todo | Candidate: warn when the cloud rate limit is hit repeatedly. |
| `stale-devices` | todo | Implement async_remove_config_entry_device or prune removed appliances. |

## Platinum (1 done, 2 todo, 0 exempt)

| Rule | Status | Notes |
|---|---|---|
| `async-dependency` | done | The client is in-tree and fully asyncio (aiohttp). |
| `inject-websession` | todo | Token check uses Home Assistant's shared session; NatureRemoAPI still opens its own session per request. |
| `strict-typing` | todo | New modules are typed; climate/light/sensor/remote/lock are not, and no strict mypy run yet. |

## Next steps, in order

1. Add `entity.py` with a shared base entity; set `_attr_has_entity_name = True` with translated names (friendly names change, entity ids do not).
2. Add availability for climate, light and sensor; audit unsubscribe-on-remove (climate local poller).
3. README: actions, setup fields, options, removal (closes the Bronze/Silver docs rules).
4. Pass Home Assistant's shared aiohttp session into `NatureRemoAPI` (inject-websession).
5. Confirm Remo mDNS (`_remo._tcp`) on the LAN and add zeroconf discovery to fill in local IPs.
6. Platform tests toward 95% coverage; strict mypy.

Note: the お知らせ (notification) toggle lives in switch.py on the main / feat/oshirase-toggle branches and in the live copy, not on local-api. This branch starts from local-api, so it does not include that switch yet; merge it in before deploying.

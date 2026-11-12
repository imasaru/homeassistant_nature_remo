# Integration Quality Scale: where this fork stands

Checked on 2026-11-13 against the 54 rules listed at
https://developers.home-assistant.io/docs/core/integration-quality-scale/rules.
The machine-readable version is `custom_components/nature_remo/quality_scale.yaml`.

**Honest tier today: below Bronze.** Every Bronze rule must be done, and these are still open:
brands (logo in the HA brands repo), common-modules (shared entity.py), has-entity-name.

Entity unique ids are unchanged on purpose, so the renamed `bottom_reeme_*` entity ids keep working.
The Fujitsu AR-RFF2J encoder and local API code are untouched.

## Bronze (15 done, 3 todo, 2 exempt)

| Rule | Status | Notes |
|---|---|---|
| `action-setup` | done | send_light_mode is registered once in async_setup. |
| `appropriate-polling` | done | 60 s default (2 cloud calls per poll, within Nature's 30 requests / 5 min), user-adjustable in options. |
| `brands` | todo | No logo/icon in home-assistant/brands custom_integrations yet. |
| `common-modules` | todo | coordinator.py exists; a shared entity.py base class does not. |
| `config-flow` | done | UI setup with token check, data_description, token in data and settings in options. |
| `config-flow-test-coverage` | done | tests/test_config_flow.py: success, each error with recovery, duplicates, reauth, reconfigure. |
| `dependency-transparency` | done | Only aiohttp, which Home Assistant ships. |
| `docs-actions` | done | README 'Actions' section. |
| `docs-conditions` | exempt | The integration provides no conditions. |
| `docs-high-level-description` | done | README describes Nature Remo and what the integration controls. |
| `docs-installation-instructions` | done | README has HACS and manual install steps. |
| `docs-removal-instructions` | done | README 'Removing the integration' section. |
| `docs-triggers` | exempt | The integration provides no triggers. |
| `entity-event-setup` | done | Listeners use async_on_remove or CoordinatorEntity; light action map cleared on removal. |
| `entity-unique-id` | done | All entities set unique ids (nature_remo_<platform>_<appliance_id>); unchanged by this branch. |
| `has-entity-name` | todo | Not set yet. Safe for entity ids (they live in the registry) but changes friendly names, so do it deliberately. |
| `runtime-data` | done | entry.runtime_data holds the API client and coordinator; hass.data is no longer used. |
| `test-before-configure` | done | Config flow calls GET /1/users/me before creating the entry. |
| `test-before-setup` | done | Setup checks the token: rejected -> ConfigEntryAuthFailed (reauth), unreachable -> ConfigEntryNotReady. |
| `unique-config-entry` | done | Nature account id is the entry unique id; old entries are matched by token and adopt the id on next setup. |

## Silver (6 done, 4 todo, 0 exempt)

| Rule | Status | Notes |
|---|---|---|
| `action-exceptions` | todo | send_light_mode raises ServiceValidationError for bad input; API failures in entity actions still only log. |
| `config-entry-unloading` | done | Platforms unload; climate local poller cancelled on unload; tested. |
| `docs-configuration-parameters` | done | README 'Options (Configure)' section. |
| `docs-installation-parameters` | done | README 'Setup fields' section. |
| `entity-unavailable` | todo | Remote reports availability; climate, light and sensor do not yet. |
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

## Platinum (2 done, 1 todo, 0 exempt)

| Rule | Status | Notes |
|---|---|---|
| `async-dependency` | done | The client is in-tree and fully asyncio (aiohttp). |
| `inject-websession` | done | NatureRemoAPI takes Home Assistant's shared aiohttp session. |
| `strict-typing` | todo | New modules are typed; climate/light/sensor/remote/switch are not, and no strict mypy run yet. |

## Next steps, in order

0. Submit a logo/icon to home-assistant/brands (custom_integrations/nature_remo) to close the last non-code Bronze rule.

1. Add `entity.py` with a shared base entity; set `_attr_has_entity_name = True` with translated names (friendly names change, entity ids do not).
2. Add availability for climate, light and sensor (entity-unavailable).
3. Confirm Remo mDNS (`_remo._tcp`) on the LAN and add zeroconf discovery to fill in local IPs.
4. Platform tests toward 95% coverage; strict mypy.

Note: main (the お知らせ toggle in switch.py and the Fujitsu footer fixes, identical to the live copy) is merged into this branch, so the toggle and encoder behave exactly as live.

## Removed: Qrio lock platform (2026-11-13)

The Phase 1 read-only lock entity for the Qrio Lock (Q-SL2) was removed: the Nature Remo API does not report or control the lock, so it was only a placeholder. `lock.py`, its `PLATFORMS` entry and the coordinator's lock parsing are gone. On the first setup after upgrading, any leftover `lock.*` entities of this integration are deleted from the entity registry (a partial step toward `stale-devices`). **When deployed, the existing `lock.bottom_reeme_*` entity disappears**; remove it from dashboards and automations first.

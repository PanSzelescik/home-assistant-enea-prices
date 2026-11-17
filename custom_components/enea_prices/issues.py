"""Repair issues of the Enea Ceny integration.

The prices are a table shipped with the integration, and the table ends on a
fixed date — the last day of the tariff the regulator approved.  Past it the
sensors report nothing and the costs the Enea Licznik integration computes
stop growing, silently.  An issue says so a little ahead of that day and for
as long as the table stays out of date; a newer release of the integration
with the next tariff makes it go away.
"""
from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ISSUE_TARIFF_TABLE_ENDED,
    ISSUE_TARIFF_TABLE_ENDING,
    RELEASES_URL,
    TARIFF_TABLE_WARNING_DAYS,
)
from .tariffs import TariffGroup


def table_issue(group: TariffGroup, today: date) -> tuple[str | None, date | None]:
    """Return the issue key the tariff table calls for today and its last day.

    None as the key when the table reaches far enough; (None, None) for a
    group with no periods at all.
    """
    if not group.periods:
        return None, None
    covered_until = max(period.valid_until for period in group.periods)
    if today > covered_until:
        return ISSUE_TARIFF_TABLE_ENDED, covered_until
    if (covered_until - today).days <= TARIFF_TABLE_WARNING_DAYS:
        return ISSUE_TARIFF_TABLE_ENDING, covered_until
    return None, covered_until


@callback
def async_update_table_issue(hass: HomeAssistant, entry_id: str, group: TariffGroup) -> None:
    """Raise the issue the tariff table calls for today and drop the other one.

    The issues are not persistent: they are raised again at every setup and
    every midnight for as long as they hold, and a restart on a newer release
    starts without them.
    """
    key, covered_until = table_issue(group, dt_util.now().date())
    for other in (ISSUE_TARIFF_TABLE_ENDING, ISSUE_TARIFF_TABLE_ENDED):
        if other != key:
            ir.async_delete_issue(hass, DOMAIN, f"{other}_{entry_id}")
    if key is None or covered_until is None:
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{key}_{entry_id}",
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        learn_more_url=RELEASES_URL,
        translation_key=key,
        translation_placeholders={
            "tariff": group.name,
            "valid_until": covered_until.isoformat(),
        },
    )


@callback
def async_delete_table_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Drop the tariff table issues of an entry that is unloaded or removed."""
    for key in (ISSUE_TARIFF_TABLE_ENDING, ISSUE_TARIFF_TABLE_ENDED):
        ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry_id}")

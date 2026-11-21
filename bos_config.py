"""Konfigurationsaenderungen eines Zeitraums: wer hat wann welchen Job oder welche Systemkonfiguration geaendert.

Quelle ist das Plugin Job Config History. Seine Sammelschnittstelle /jobConfigHistory/api/json?filter=all liefert
in einer Abfrage alle Eintraege aller Jobs (auch geloeschter) und der Systemkonfiguration; den Zeitraum und das
Konto filtert das Werkzeug.
"""
import datetime
import os
import urllib.parse
import zoneinfo

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp
from mcp_jenkins.server.bos_builds import _bound

TIMEOUT = 60
MAX_RESULTS = 500
# Zeitzone, in der Jenkins die Zeitpunkte des Plugins schreibt (JVM-Standard des Controllers)
SERVER_ZONE = zoneinfo.ZoneInfo(os.environ.get('JENKINS_TIME_ZONE', 'Europe/Berlin'))
OPERATIONS = {
    'changed': 'changed', 'geändert': 'changed', 'created': 'created', 'erstellt': 'created',
    'renamed': 'renamed', 'umbenannt': 'renamed', 'deleted': 'deleted', 'gelöscht': 'deleted',
}


def _moment(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d_%H-%M-%S').replace(tzinfo=SERVER_ZONE)
    except (TypeError, ValueError):
        return None


def _entry_url(root: str, client, entry: dict) -> str | None:
    name = entry.get('job') or ''
    if entry.get('isJob'):
        if '_deleted_' in name:
            return None
        return f"{root}{client._job_path(name)}/jobConfigHistory/"
    return f"{root}jobConfigHistory/history?name={urllib.parse.quote(name)}"


@mcp.tool(tags=['read'])
async def list_config_changes(ctx: Context, date_from: str, date_to: str = '', changed_by: str = 'me',
                              item_contains: str = '', time_zone: str = 'Europe/Berlin') -> dict:
    """List the configuration changes of a period: who created, changed, renamed or deleted which job, and changes
    of the system configuration (Jenkins, nodes, plugins), from the Job Config History plugin, in one call

    Use this for "what did I change in Jenkins" and "who changed job X"; list_builds covers the builds.

    Args:
        date_from: Day as YYYY-MM-DD (or an ISO date-time), inclusive, in time_zone.
        date_to: Last day, inclusive; empty means the day of date_from.
        changed_by: "me" for the account this request runs as, or Jenkins user ids or full names separated by
            commas; empty means every account (SYSTEM marks changes Jenkins made itself).
        item_contains: Only jobs or configuration files whose name contains this text (case-insensitive).
        time_zone: Time zone of the days and of the times in the answer (default Europe/Berlin).

    Returns:
        caller, period, changes_in_period (all accounts), total, complete, by_operation, by_item, and changes oldest
        first: time, item, kind (job or system), operation (created, changed, renamed, deleted, or the plugin's
        text), user_id, user_name, comment, old_name and new_name for a rename, url of the item's history (none for
        a deleted job). complete is false when the answer was cut at 500 changes.
    """
    try:
        zone = zoneinfo.ZoneInfo(time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f'unknown time_zone {time_zone!r}') from e
    start = _bound(date_from, zone, end=False)
    end = _bound(date_to or date_from, zone, end=True)
    if end < start:
        raise ValueError('date_to lies before date_from')

    client = jenkins(ctx)
    client.timeout = max(getattr(client, 'timeout', 0) or 0, TIMEOUT)
    me = client.request('GET', 'me/api/json', params={'tree': 'id,fullName,absoluteUrl'}, crumb=False).json()
    caller = {'id': me.get('id'), 'name': me.get('fullName')}
    wanted: set[str] = set()
    for name in (n.strip() for n in changed_by.split(',')):
        if name.casefold() == 'me':
            wanted |= {str(caller['id'] or '').casefold(), str(caller['name'] or '').casefold()} - {''}
        elif name:
            wanted.add(name.casefold())
    # Jenkins' own root URL, as in the url of a build, not the address this server reaches Jenkins under
    absolute = str(me.get('absoluteUrl') or '')
    root = absolute.rsplit('/user/', 1)[0] + '/' if '/user/' in absolute else client.endpoint_url('').rstrip('/') + '/'

    configs = client.request('GET', 'jobConfigHistory/api/json', params={'filter': 'all'}, crumb=False).json()
    in_period = 0
    changes: list[dict] = []
    for entry in configs.get('configs') or []:
        moment = _moment(entry.get('date'))
        if moment is None or not start <= moment <= end:
            continue
        in_period += 1
        item = entry.get('job') or ''
        if item_contains.strip() and item_contains.strip().casefold() not in item.casefold():
            continue
        users = {str(entry.get('userID') or '').casefold(), str(entry.get('user') or '').casefold()} - {''}
        if wanted and not users & wanted:
            continue
        operation = str(entry.get('operation') or '')
        change = {
            'time': moment.astimezone(zone).isoformat(timespec='seconds'), 'item': item,
            'kind': 'job' if entry.get('isJob') else 'system',
            'operation': OPERATIONS.get(operation.casefold(), operation),
            'user_id': entry.get('userID'), 'user_name': entry.get('user'),
            'comment': entry.get('changeReasonComment') or None, 'url': _entry_url(root, client, entry),
        }
        if entry.get('oldName') or entry.get('currentName'):
            change['old_name'], change['new_name'] = entry.get('oldName') or None, entry.get('currentName') or None
        changes.append(change)
    changes.sort(key=lambda c: c['time'])
    by_operation: dict[str, int] = {}
    by_item: dict[str, int] = {}
    for change in changes:
        by_operation[change['operation']] = by_operation.get(change['operation'], 0) + 1
        by_item[change['item']] = by_item.get(change['item'], 0) + 1
    total = len(changes)
    return {'caller': caller, 'period': {'from': start.isoformat(timespec='seconds'), 'to': end.isoformat(timespec='seconds')},
            'changes_in_period': in_period, 'total': total, 'complete': total <= MAX_RESULTS,
            'by_operation': by_operation, 'by_item': by_item, 'changes': changes[:MAX_RESULTS]}

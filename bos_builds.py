"""Builds eines Zeitraums ueber alle Jobs: wer hat wann was gestartet, in einem Aufruf.

Ohne dieses Werkzeug liefern die Werkzeuge von mcp-jenkins Zeitpunkt und Ausloeser nur je einzelnem Build; eine Frage
wie "welche Builds habe ich am 05.11. gestartet" brauchte einen Aufruf je Job und Build.
"""
import datetime
import re
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp

PAGE = 100            # Builds je Abfrage (allBuilds{a,b})
MAX_PER_JOB = 2000    # aeltere Builds eines Jobs liest das Werkzeug nicht mehr
MAX_RESULTS = 500     # Builds in der Antwort
WORKERS = 2
TIMEOUT = 30          # Sekunden je Abfrage; allBuilds mit Ausloesern braucht bei grossen Jobs mehr als die 5 s von mcp-jenkins
TREE = ('allBuilds[number,timestamp,duration,result,building,url,'
        'actions[causes[_class,userId,userName,shortDescription,upstreamProject,upstreamBuild]]]{%d,%d}')


def _bound(value: str, zone: zoneinfo.ZoneInfo, end: bool) -> datetime.datetime:
    value = value.strip()
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            day = datetime.date.fromisoformat(value)
            moment = datetime.datetime.combine(day, datetime.time.max if end else datetime.time.min, zone)
            return moment.replace(microsecond=999000 if end else 0)
        moment = datetime.datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f'{value!r} is neither YYYY-MM-DD nor an ISO date-time') from e
    return moment if moment.tzinfo else moment.replace(tzinfo=zone)


def _causes(build: dict) -> list[dict]:
    return [cause for action in build.get('actions') or [] if isinstance(action, dict)
            for cause in action.get('causes') or []]


def _started_by(causes: list[dict]) -> dict[str, Any]:
    """Ausloeser eines Builds: Benutzer (user_id, user_name) oder die Beschreibung des Ausloesers."""
    out: dict[str, Any] = {}
    for cause in causes:
        if cause.get('userId') or cause.get('userName'):
            out.setdefault('user_id', cause.get('userId'))
            out.setdefault('user_name', cause.get('userName'))
        elif cause.get('upstreamProject'):
            out.setdefault('upstream', f"{cause['upstreamProject']} #{cause.get('upstreamBuild')}")
        if cause.get('shortDescription'):
            out.setdefault('cause', cause['shortDescription'])
    return out


def _user_matches(started: dict, wanted: set[str]) -> bool:
    names = {str(started.get(key) or '').casefold() for key in ('user_id', 'user_name')} - {''}
    return bool(names & wanted)


def _job_builds(client, fullname: str, start_ms: int, end_ms: int) -> tuple[list[dict], bool]:
    """Builds eines Jobs im Zeitraum, neueste zuerst gelesen; True, wenn MAX_PER_JOB den Zeitraum abschneidet."""
    found: list[dict] = []
    for offset in range(0, MAX_PER_JOB, PAGE):
        response = client.request('GET', f'{client._job_path(fullname)}/api/json',
                                  params={'tree': TREE % (offset, offset + PAGE)}, crumb=False)
        builds = response.json().get('allBuilds')
        if not builds:
            return found, False
        for build in builds:
            if start_ms <= (build.get('timestamp') or 0) <= end_ms:
                found.append(build)
        oldest = min(build.get('timestamp') or 0 for build in builds)
        if oldest < start_ms or len(builds) < PAGE:
            return found, False
    return found, True


@mcp.tool(tags=['read'])
async def list_builds(ctx: Context, date_from: str, date_to: str = '', started_by: str = '',
                      job_contains: str = '', time_zone: str = 'Europe/Berlin') -> dict:
    """List the builds of all jobs (all folders) that started in a period, with result and who or what started them

    Use this for "which builds ran / failed on <day>" and "which builds did I start"; it replaces get_item and
    get_build calls job by job. A build's own record is the source: no console output is read.

    Args:
        date_from: Day as YYYY-MM-DD (or an ISO date-time), inclusive, in time_zone.
        date_to: Last day, inclusive; empty means the day of date_from.
        started_by: Only builds a user started by hand: "me" for the account this request runs as, or a Jenkins
            user id or full name; several separated by commas. Empty: every build, with its cause (user, timer,
            SCM change, upstream build).
        job_contains: Only jobs whose full name contains this text (case-insensitive).
        time_zone: Time zone of the days and of the times in the answer (default Europe/Berlin).

    Returns:
        caller (the account this request runs as), period, jobs_scanned, builds_in_period (all jobs, before the
        started_by filter), total, complete, by_result, and builds oldest first: job, number, start, duration_s,
        result (null while running), started_by, url. complete is false when a job had more builds than the tool
        reads or the answer was cut at 500 builds.
    """
    try:
        zone = zoneinfo.ZoneInfo(time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f'unknown time_zone {time_zone!r}') from e
    start = _bound(date_from, zone, end=False)
    end = _bound(date_to or date_from, zone, end=True)
    if end < start:
        raise ValueError('date_to lies before date_from')
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    client = jenkins(ctx)
    client.timeout = max(getattr(client, 'timeout', 0) or 0, TIMEOUT)  # Client gilt nur fuer diese Anfrage
    me = client.request('GET', 'me/api/json', params={'tree': 'id,fullName'}, crumb=False).json()
    caller = {'id': me.get('id'), 'name': me.get('fullName')}
    wanted: set[str] = set()
    for name in (n.strip() for n in started_by.split(',')):
        if name.casefold() == 'me':
            wanted |= {str(caller['id'] or '').casefold(), str(caller['name'] or '').casefold()} - {''}
        elif name:
            wanted.add(name.casefold())

    jobs = [item.model_dump(exclude_none=True) for item in client.get_items()]
    jobs = [job for job in jobs if 'color' in job]  # Ordner und Multibranch-Projekte haben keine eigenen Builds
    if job_contains.strip():
        jobs = [job for job in jobs if job_contains.strip().casefold() in job['fullname'].casefold()]

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(lambda job: _job_builds(client, job['fullname'], start_ms, end_ms), jobs))

    complete = True
    in_period = 0
    builds: list[dict] = []
    for job, (found, cut) in zip(jobs, results):
        complete &= not cut
        in_period += len(found)
        for build in found:
            started = _started_by(_causes(build))
            if wanted and not _user_matches(started, wanted):
                continue
            builds.append({
                'job': job['fullname'], 'number': build.get('number'),
                'start': datetime.datetime.fromtimestamp(build['timestamp'] / 1000, zone).isoformat(timespec='seconds'),
                'duration_s': round((build.get('duration') or 0) / 1000),
                'result': None if build.get('building') else build.get('result'),
                'started_by': started, 'url': build.get('url'),
            })
    builds.sort(key=lambda b: b['start'])
    by_result: dict[str, int] = {}
    for build in builds:
        key = build['result'] or 'RUNNING'
        by_result[key] = by_result.get(key, 0) + 1
    total = len(builds)
    if total > MAX_RESULTS:
        complete = False
        builds = builds[:MAX_RESULTS]
    return {'caller': caller, 'period': {'from': start.isoformat(timespec='seconds'),
                                         'to': end.isoformat(timespec='seconds')},
            'jobs_scanned': len(jobs), 'builds_in_period': in_period, 'total': total, 'complete': complete,
            'by_result': by_result, 'builds': builds}

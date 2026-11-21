"""Mehrere Builds in einem Aufruf: Daten, Parameter, Ausloeser und auf Wunsch die Konsole.

Ohne dieses Werkzeug braucht jeder Build get_build, get_build_parameters und get_build_console_output einzeln.
Builds desselben Jobs liest das Werkzeug mit einer Abfrage von allBuilds{a,b} (Jenkins' tree-Bereich), einen
einzelnen Build mit einer Abfrage seiner Build-Seite; die Konsole hat in Jenkins keine Sammelabfrage und wird je
Build gelesen.
"""
from concurrent.futures import ThreadPoolExecutor
import datetime
import zoneinfo

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp
from mcp_jenkins.server.bos_builds import _causes, _started_by

MAX_BUILDS = 50
PAGE = 100
MAX_PER_JOB = 2000
WORKERS = 2
TIMEOUT = 30
MAX_TAIL = 500
FIELDS = ('number,timestamp,duration,result,building,url,displayName,description,'
          'actions[parameters[name,value],causes[_class,userId,userName,shortDescription,upstreamProject,upstreamBuild]]')


def _parameters(build: dict) -> dict:
    for action in build.get('actions') or []:
        if isinstance(action, dict) and 'parameters' in action:
            return {p.get('name'): p.get('value') for p in action.get('parameters') or []}
    return {}


def _job_builds(client, fullname: str, numbers: set[int]) -> dict[int, dict]:
    """Die angefragten Builds eines Jobs, gelesen aus allBuilds von neu nach alt."""
    path = client._job_path(fullname)
    if len(numbers) == 1:
        (number,) = numbers
        response = client.request('GET', f'{path}/{number}/api/json', params={'tree': FIELDS}, crumb=False)
        return {number: response.json()}
    found: dict[int, dict] = {}
    lowest = min(numbers)
    for offset in range(0, MAX_PER_JOB, PAGE):
        response = client.request('GET', f'{path}/api/json',
                                  params={'tree': f'allBuilds[{FIELDS}]{{{offset},{offset + PAGE}}}'}, crumb=False)
        builds = response.json().get('allBuilds') or []
        for build in builds:
            if build.get('number') in numbers:
                found[build['number']] = build
        if not builds or len(found) == len(numbers) or len(builds) < PAGE \
                or min(b.get('number') or 0 for b in builds) <= lowest:
            break
    return found


def _console(client, fullname: str, number: int, pattern: str | None, tail: int) -> dict:
    text = client.get_build_console_output(fullname=fullname, number=number, pattern=pattern or None)
    lines = text.splitlines()
    return {'console_lines': len(lines), 'console': '\n'.join(lines[-tail:])}


@mcp.tool(tags=['read'])
async def get_builds(ctx: Context, builds: list[dict], console_tail: int = 0, console_pattern: str = '',
                     time_zone: str = 'Europe/Berlin') -> dict:
    """Get several builds in one call: result, start, duration, who or what started them, parameters, and optionally
    the end of their console output

    Use this instead of get_build, get_build_parameters and get_build_console_output build by build.

    Args:
        builds: Up to 50 builds as {"fullname": "<job full name>", "number": <build number>}.
        console_tail: Also return the last this many lines of each console output (after console_pattern), at most
            500; 0 reads no console.
        console_pattern: Optional regex; only matching console lines count for console_tail.
        time_zone: Time zone of the start times (default Europe/Berlin).

    Returns:
        count, failed and builds in the order asked: fullname, number, and either error or start, duration_s,
        result (null while running), started_by, parameters, description, url, and with console_tail console_lines
        (matching lines in all) and console.
    """
    if not builds:
        raise ValueError('builds must name at least one build')
    if len(builds) > MAX_BUILDS:
        raise ValueError(f'builds has {len(builds)} entries, at most {MAX_BUILDS} per call')
    if not 0 <= console_tail <= MAX_TAIL:
        raise ValueError(f'console_tail must be between 0 and {MAX_TAIL}')
    try:
        zone = zoneinfo.ZoneInfo(time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f'unknown time_zone {time_zone!r}') from e
    wanted: list[tuple[str, int]] = []
    for entry in builds:
        fullname, number = str(entry.get('fullname') or '').strip(), entry.get('number')
        if not fullname or not isinstance(number, int):
            raise ValueError(f'each build needs fullname and an integer number, got {entry!r}')
        wanted.append((fullname, number))

    client = jenkins(ctx)
    client.timeout = max(getattr(client, 'timeout', 0) or 0, TIMEOUT)
    by_job: dict[str, set[int]] = {}
    for fullname, number in wanted:
        by_job.setdefault(fullname, set()).add(number)

    def read_job(fullname: str):
        try:
            return fullname, _job_builds(client, fullname, by_job[fullname]), None
        except Exception as e:  # noqa: BLE001 - ein Job ohne Zugriff soll die anderen nicht abbrechen
            return fullname, {}, str(e)

    with ThreadPoolExecutor(WORKERS) as pool:
        jobs = {name: (found, error) for name, found, error in pool.map(read_job, list(by_job))}

    out: list[dict] = []
    for fullname, number in wanted:
        found, error = jobs[fullname]
        build = found.get(number)
        if build is None:
            out.append({'fullname': fullname, 'number': number, 'error': error or 'build not found'})
            continue
        out.append({
            'fullname': fullname, 'number': number,
            'start': datetime.datetime.fromtimestamp((build.get('timestamp') or 0) / 1000, zone).isoformat(timespec='seconds'),
            'duration_s': round((build.get('duration') or 0) / 1000),
            'result': None if build.get('building') else build.get('result'),
            'started_by': _started_by(_causes(build)), 'parameters': _parameters(build),
            'description': build.get('description'), 'url': build.get('url'),
        })

    if console_tail:
        def read_console(entry: dict):
            if 'error' in entry:
                return
            try:
                entry.update(_console(client, entry['fullname'], entry['number'], console_pattern, console_tail))
            except Exception as e:  # noqa: BLE001
                entry['console_error'] = str(e)

        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(read_console, out))

    return {'count': len(out), 'failed': sum(1 for entry in out if 'error' in entry), 'builds': out}

"""Listenabgleich fuer Jenkins: viele Jobnamen in einem Aufruf pruefen.

Das Modell gibt die ganze Liste in einem Aufruf ab; der Server holt die Jobliste einmal und gleicht ab.
"""
import json
import re
from typing import Any

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp

MAX_TERMS = 1000
MAX_HITS = 20


def parse_terms(raw: Any) -> list[str]:
    """JSON-Liste oder durch Komma, Semikolon oder Zeilenumbruch getrennte Werte; ohne Leere und Doppelte."""
    if isinstance(raw, list):
        items = [str(item) for item in raw]
    else:
        text = str(raw or '').strip()
        items = []
        if text.startswith('['):
            try:
                parsed = json.loads(text)
                items = [str(item) for item in parsed] if isinstance(parsed, list) else []
            except ValueError:
                items = []
        if not items:
            items = re.split(r'[,;\n]+', text)
    seen: set[str] = set()
    out: list[str] = []
    for item in (i.strip() for i in items):
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def word_match(term: str, text: str) -> bool:
    """Ganzes Wort: "deploy-1" trifft nicht "deploy-12"."""
    return re.search(r'(?i)(^|[^\w])' + re.escape(term) + r'($|[^\w])', text or '') is not None


@mcp.tool(tags=['read'])
async def job_check_list(ctx: Context, values: str, match: str = 'name', only_missing: bool = False) -> dict:
    """Check a whole list of job names against all Jenkins items (all folders) in one call

    Use this instead of one get_item or query_items call per name.

    Args:
        values: Job names, full names or name parts, separated by commas or new lines; a JSON array of strings
            is accepted too. At most 1000.
        match: "name" (default) compares the job name, "fullname" the full path (folder/job), "word" finds the
            value as a whole word in the full name ("deploy-1" does not match "deploy-12").
        only_missing: Return only the values without a match.

    Returns:
        items_scanned, values_checked, found_count, missing_count, missing and, unless only_missing,
        found: value -> matching items (fullname, color, url; at most 20 per value)
    """
    terms = parse_terms(values)
    if not terms:
        raise ValueError('values is empty')
    if len(terms) > MAX_TERMS:
        raise ValueError(f'At most {MAX_TERMS} values per call, got {len(terms)}')
    if match not in ('name', 'fullname', 'word'):
        raise ValueError('match must be "name", "fullname" or "word"')
    items = [item.model_dump(exclude_none=True) for item in jenkins(ctx).get_items()]
    found: dict[str, list[dict]] = {}
    for term in terms:
        wanted = term.strip('/').lower()
        for item in items:
            fullname = item.get('fullname') or item.get('name', '')
            if match == 'name':
                hit = item.get('name', '').lower() == wanted
            elif match == 'fullname':
                hit = fullname.lower() == wanted
            else:
                hit = word_match(term, fullname)
            if hit and len(found.setdefault(term, [])) < MAX_HITS:
                found[term].append({key: item.get(key) for key in ('fullname', 'color', 'url') if item.get(key)})
    missing = [term for term in terms if term not in found]
    result: dict[str, Any] = {'items_scanned': len(items), 'values_checked': len(terms),
                              'found_count': len(found), 'missing_count': len(missing), 'missing': missing}
    if not only_missing:
        result['found'] = found
    return result

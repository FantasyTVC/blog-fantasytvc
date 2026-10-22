#!/usr/bin/env python3
"""TVC Sleeper sync: safe read-only export for GitHub Actions."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

API = 'https://api.sleeper.app/v1'
LEAGUE = '1322389661489856512'


def get(path):
    req = urllib.request.Request(API + path, headers={'User-Agent': 'TVC-Stats-Lab/0.1', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def run(outdir):
    league = get(f'/league/{LEAGUE}')
    users = get(f'/league/{LEAGUE}/users')
    rosters = get(f'/league/{LEAGUE}/rosters')
    if str(league.get('season')) != '2026':
        raise ValueError('La liga no corresponde a la temporada 2026; se cancela para proteger los datos.')
    user_by_id = {u['user_id']: u for u in users}
    roster_by_id = {r['roster_id']: r for r in rosters}
    scored = int((league.get('settings') or {}).get('last_scored_leg') or 0)
    scored = min(max(scored, 0), 18)
    results = []
    pending = []
    for week in range(1, scored + 1):
        rows = get(f'/league/{LEAGUE}/matchups/{week}')
        by_matchup = {}
        for row in rows:
            mid = row.get('matchup_id')
            if mid is not None:
                by_matchup.setdefault(mid, []).append(row)
        complete = len(by_matchup) == 6 and len(rows) == 12 and all(
            len(group) == 2 and all(isinstance(r.get('points'), (int, float)) and not isinstance(r.get('points'), bool) for r in group)
            for group in by_matchup.values()
        )
        if not complete:
            pending.append({'week': week, 'reason': 'No se encontraron 6 enfrentamientos completos de 12 equipos'})
            continue
        for matchup_id, group in sorted(by_matchup.items(), key=lambda pair: str(pair[0])):
            a, b = sorted(group, key=lambda r: r['roster_id'])
            for own, rival in [(a, b), (b, a)]:
                roster = roster_by_id.get(own['roster_id'], {})
                user = user_by_id.get(roster.get('owner_id'), {})
                results.append({
                    'season': 2026, 'week': week, 'matchup_id': matchup_id,
                    'roster_id': own['roster_id'], 'owner_id': roster.get('owner_id'),
                    'team_name': (roster.get('metadata') or {}).get('team_name') or (user.get('metadata') or {}).get('team_name') or user.get('display_name') or f"Roster {own['roster_id']}",
                    'opponent_roster_id': rival['roster_id'],
                    'points': own['points'], 'opponent_points': rival['points'],
                    'starters': own.get('starters') or [],
                    'starters_points': own.get('starters_points') or [],
                    'players': own.get('players') or [],
                    'players_points': own.get('players_points') or {},
                })
    results.sort(key=lambda x: (x['week'], x['roster_id']))
    keys = [(x['season'], x['week'], x['roster_id']) for x in results]
    if len(keys) != len(set(keys)):
        raise ValueError('Se detectaron registros duplicados; exportación cancelada.')
    payload = {
        'schema_version': 1, 'source': 'Sleeper API', 'league_id': LEAGUE,
        'season': 2026, 'generated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'last_scored_week': scored, 'complete_weeks': sorted({x['week'] for x in results}),
        'pending_weeks': pending, 'total_team_week_rows': len(results), 'results': results,
    }
    outdir.mkdir(parents=True, exist_ok=True)
    dest = outdir / 'sleeper_2026_preview.json'
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Archivo: {dest}')
    print(f'Jornadas completas: {payload["complete_weeks"]}')
    print(f'Jornadas pendientes: {pending}')
    print(f'Registros equipo-semana: {len(results)}')
    if not results:
        raise ValueError('No hay jornadas completas para validar. No se publican datos.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/preview')
    args = parser.parse_args()
    try:
        run(Path(args.output))
    except (ValueError, urllib.error.URLError, KeyError, TypeError) as exc:
        print(f'ERROR de sincronización: {exc}', file=sys.stderr)
        sys.exit(1)

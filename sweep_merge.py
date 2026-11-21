"""Merge the results of all sweep slices and queue new finds for the regular scan.

Usage: python3 sweep_merge.py DIR_WITH_HITS_FILES
- sweep_found.json keeps every app the sweep has found (id -> store, name, version, date, queued).
- Up to CAP not-yet-queued finds are added to submissions.json as "sweep-<id>" suggestions with the app's
  store link; the regular scan then reads each one's version history and adds it with its real date if its
  notes really mention iPhone Duo (a find alone adds nothing to the site).
- sweep_last.json holds the totals of the latest sweep (shown in the scan email and handy for checks).
- leads.json (read by tomorrow's sweep): the developers of every app on the site or found by the sweep, so their
  other apps are checked too. Third-party Duo lists are never used as input (they are only benchmarks).
"""
import datetime, glob, json, os, re, subprocess, sys, time

def curl(url):
    r = subprocess.run(['curl', '-sL', '--compressed', '-m', '90', '-A', 'Mozilla/5.0', url], capture_output=True)
    return r.stdout.decode('utf-8', 'replace')

def site_developers(ids):
    """Developer ids of the apps on the site (Apple lookup, 200 at a time)."""
    out = set()
    for k in range(0, len(ids), 200):
        try: res = json.loads(curl('https://itunes.apple.com/lookup?country=us&id=' + ','.join(ids[k:k + 200]))).get('results', [])
        except ValueError: res = []
        out |= {str(a['artistId']) for a in res if a.get('artistId')}
        time.sleep(1)
    return out

CAP = 1500  # finds queued per day, so the regular scan is not swamped while the backlog is large

def load(path, default):
    try: return json.load(open(path))
    except (OSError, ValueError): return default

def main():
    folder = sys.argv[1]
    today = datetime.date.today().isoformat()
    rows = {str(r['id']) for r in load('data.json', {'rows': []})['rows']}
    found = load('sweep_found.json', {})
    subs = load('submissions.json', [])
    have_mid = {s.get('mid') for s in subs}
    totals, shards, new = {}, 0, 0
    for f in sorted(glob.glob(os.path.join(folder, '**', 'hits-*.json'), recursive=True)):
        part = load(f, {})
        shards += 1
        for k, v in part.get('stats', {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k != 'shard': totals[k] = totals.get(k, 0) + v
            if k == 'stopped_early' and v: totals['slices_stopped_early'] = totals.get('slices_stopped_early', 0) + 1
        for h in part.get('hits', []):
            if h['id'] not in found:
                found[h['id']] = {'cc': h['cc'], 'app': h['app'], 'version': h['version'], 'date': h['date'], 'found': today, 'queued': '',
                                  'artist': h.get('artist', ''), 'how': h.get('how', 'newest notes')}
                new += 1
    queued = 0
    # new Duo-specific apps (confirmed by their description) first, then the oldest finds
    for i, f in sorted(found.items(), key=lambda kv: (kv[1].get('how') != 'description', kv[1]['found'])):
        if queued >= CAP: break
        if f['queued'] or i in rows: continue
        mid = 'sweep-' + i
        if mid not in have_mid:
            subs.append({'mid': mid, 'date': today, 'app': f['app'][:80], 'link': f'https://apps.apple.com/{f["cc"]}/app/id{i}'})
        f['queued'] = today; queued += 1
    waiting = sum(1 for i, f in found.items() if not f['queued'] and i not in rows)
    json.dump(found, open('sweep_found.json', 'w'), ensure_ascii=False, indent=0, sort_keys=True)
    # leads for tomorrow: the developers of site apps and finds (their other apps are checked too)
    devs = {f.get('artist') for f in found.values() if f.get('artist')} | site_developers(sorted(rows))
    json.dump({'date': today, 'developers': sorted(d for d in devs if d.isdigit()), 'apps': []}, open('leads.json', 'w'))
    totals['lead_developers'] = len(devs)
    json.dump(subs, open('submissions.json', 'w'), ensure_ascii=False, indent=1)
    last = {'date': today, 'slices': shards, **totals, 'new_finds': new, 'queued_today': queued, 'waiting_to_queue': waiting, 'found_total': len(found)}
    json.dump(last, open('sweep_last.json', 'w'), indent=1)
    print(json.dumps(last))

if __name__ == '__main__':
    main()

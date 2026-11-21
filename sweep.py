"""Daily sweep of the whole App Store for apps that mention iPhone Duo in their update notes.

Why: the regular scan (duo_cloud.py) only sees about 34,000 chart apps. This script takes one slice of:
  - Apple's public lists of every app and of new apps (apps.apple.com sitemaps, about 1.9 million apps),
  - searches for new Duo-specific apps (SEARCH_TERMS in every market, spread over the slices),
  - leads (leads.json, built by sweep_merge.py): the other apps of developers already on the site or found
    by the sweep (third-party Duo lists are never used as input; they are only benchmarks),
looks the apps up 200 at a time, and keeps an app only if it was updated since 1 Sep 2026, can run on iPhone Duo
and is not on the site. Then:
  1. newest notes mention iPhone Duo (duo_hit) -> a find;
     or, for an app first released since 1 Sep 2026, its own App Store description mentions it -> a find;
  2. otherwise its version history is read (leads first, then the most-rated apps), once per app, within the time
     left; an older version mentioning iPhone Duo -> a find, dated by that version.
The ids whose history was read are kept in hist-done-SHARD.txt (restored from the Actions cache each day).
Finds are only leads: sweep_merge.py queues them in submissions.json and the regular scan verifies each one.

Usage: python3 sweep.py SHARD SHARDS OUT.json [--minutes 150]
"""
import base64, datetime, gzip, json, os, re, subprocess, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import duo_cloud as d

# searches for new Duo-specific apps that are in no list or chart yet (run in every market, spread over the slices)
SEARCH_TERMS = ['iPhone Duo', 'Duo', 'for Duo', 'Duo app', 'Duo game', 'Duo widget', 'Duo wallpaper', 'Duo keyboard', 'Duo browser',
    'Duo camera', 'Duo clock', 'Duo notes', 'Duo split', 'Duo screen', 'fold', 'foldable', 'foldable iPhone', 'folding phone', 'fold game',
    'fold counter', 'fold clock', 'fold tracker', 'unfold', 'unfolded', 'hinge', 'hinge counter', 'outer screen', 'cover screen',
    'inner display', 'two screens', 'dual screen', 'split screen', 'split view', 'side by side', 'book mode', 'tabletop mode', 'half open',
    'flip clock', 'widescreen', 'big screen', 'mini laptop', 'pocket mac', 'trackpad', 'second screen', 'multitasking', 'two player',
    'games for two', 'duo wallpaper', 'fold wallpaper', 'fold stats', 'fold ring', 'fold notes', 'fold camera', 'foldable game',
    'foldable keyboard', 'foldable browser', 'made for Duo', 'optimized for Duo', 'built for Duo', 'iPhone fold', 'new iPhone',
    'iOS 27', 'iOS 27.1', 'Liquid Glass']

INDEXES = ['https://apps.apple.com/sitemaps_apps_index_app_1.xml', 'https://apps.apple.com/sitemaps_apps_index_new-app_1.xml']
HIST_THREADS = 3

def fetch(url, binary=False):
    for i in range(4):
        r = subprocess.run(['curl', '-sL', '--compressed', '-m', '90', '-A', d.UA, url], capture_output=True)
        if r.returncode == 0 and r.stdout: return r.stdout if binary else r.stdout.decode('utf-8', 'replace')
        time.sleep(5 * (i + 1))
    return b'' if binary else ''

def lookup(cc, ids, stats):
    """Apple lookup for up to 200 ids; waits and retries when Apple slows us down."""
    for i in range(5):
        r = subprocess.run(['curl', '-s', '-m', '90', '-w', '\n%{http_code}', f'https://itunes.apple.com/lookup?country={cc}&id=' + ','.join(ids)],
                           capture_output=True)
        body, _, code = r.stdout.decode('utf-8', 'replace').rpartition('\n')
        if code == '200':
            try: return json.loads(body).get('results', [])
            except ValueError: pass
        if code in ('403', '429', '503'): stats['slowed'] += 1
        time.sleep(10 * (i + 1))
    stats['failed_lookups'] += 1
    return None

def developer_apps(artist, stats):
    """All apps of one developer (Apple lookup by developer id)."""
    for i in range(3):
        r = subprocess.run(['curl', '-s', '-m', '90', '-w', '\n%{http_code}', f'https://itunes.apple.com/lookup?id={artist}&entity=software&limit=200&country=us'],
                           capture_output=True)
        body, _, code = r.stdout.decode('utf-8', 'replace').rpartition('\n')
        if code == '200':
            try: return [str(a['trackId']) for a in json.loads(body).get('results', []) if a.get('wrapperType') == 'software']
            except ValueError: pass
        if code in ('403', '429', '503'): stats['slowed'] += 1
        time.sleep(10 * (i + 1))
    return []

def search(term, cc, stats):
    """App Store search (rate-limited by Apple, so slow and patient)."""
    for i in range(3):
        r = subprocess.run(['curl', '-s', '-m', '60', '-w', '\n%{http_code}', f'https://itunes.apple.com/search?country={cc}&entity=software&limit=200&term=' + urllib.parse.quote(term)],
                           capture_output=True)
        body, _, code = r.stdout.decode('utf-8', 'replace').rpartition('\n')
        if code == '200':
            try: return json.loads(body).get('results', [])
            except ValueError: pass
        if code in ('403', '429', '503'): stats['slowed'] += 1
        time.sleep(20 * (i + 1))
    return []

LIVE_EVERY = 30 * 60   # finds are saved for the website every 30 minutes

def save_live(shard, rows):
    """Save this slice's finds so far to the 'live' branch (live/<shard>.json); the publisher adds them to the site."""
    repo, path = os.environ.get('GITHUB_REPOSITORY', ''), f'live/{shard}.json'
    if not repo: json.dump(rows, open(f'live-{shard}.json', 'w'), ensure_ascii=False); return True   # local test
    body = base64.b64encode(json.dumps({'rows': rows}, ensure_ascii=False).encode()).decode()
    for i in range(4):
        sha = subprocess.run(['gh', 'api', f'repos/{repo}/contents/{path}?ref=live', '--jq', '.sha'], capture_output=True, text=True).stdout.strip()
        req = {'message': f'live finds, slice {shard}', 'content': body, 'branch': 'live'}
        if sha and not sha.startswith('{'): req['sha'] = sha
        r = subprocess.run(['gh', 'api', '-X', 'PUT', f'repos/{repo}/contents/{path}', '--input', '-'], input=json.dumps(req), capture_output=True, text=True)
        if r.returncode == 0: return True
        time.sleep(10 * (i + 1))
    return False

def make_rows(finds, found, stats):
    """Complete site rows for finds: details from the lookup, ratings and availability in every market."""
    ids = [h['id'] for h in finds]; mk = {}
    for cc in d.MARKETS:
        for k in range(0, len(ids), 200):
            for a in lookup(cc, ids[k:k + 200], stats) or []:
                mk.setdefault(str(a['trackId']), {})[cc] = [round(a.get('averageUserRating', 0), 1), a.get('userRatingCount', 0)]
            time.sleep(0.3)
    today = datetime.date.today().isoformat(); rows = []
    for h in finds:
        cc, a = found[h['id']]
        up, rel = (a.get('currentVersionReleaseDate') or '')[:10], (a.get('releaseDate') or '')[:10]
        r = {'app': a.get('trackName', ''), 'art': a.get('artworkUrl100', ''), 'category': a.get('primaryGenreName', ''),
             'desc': d.one_line(a.get('description', '')), 'developer': a.get('artistName', ''), 'duo_date': min(h['date'], up) if up else h['date'],
             'duo_version': '' if h['how'] == 'description' else h['version'], 'first_seen': today, 'hist_ok': True, 'home': cc, 'id': h['id'],
             'markets': '', 'min_ios': a.get('minimumOsVersion', ''), 'mk': mk.get(h['id'], {}), 'note': h['note'],
             'price': a.get('formattedPrice', ''), 'rating': round(a.get('averageUserRating', 0), 1), 'ratings': a.get('userRatingCount', 0),
             'released': rel, 'updated': up, 'url': a.get('trackViewUrl', '').split('?')[0], 'version': a.get('version', '')}
        if h['how'] == 'description': r['how'] = 'description'
        rows.append(r)
    return rows

def page(i, cc):
    """(http code, version history) of an app's store page."""
    r = subprocess.run(['curl', '-sL', '--compressed', '-m', '60', '-A', d.UA, '-w', '\n%{http_code}', f'https://apps.apple.com/{cc}/app/id{i}'], capture_output=True)
    body, _, code = r.stdout.decode('utf-8', 'replace').rpartition('\n')
    return code, (d.parse_history(body) if code == '200' else [])

def main():
    shard, shards, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    minutes = float(sys.argv[sys.argv.index('--minutes') + 1]) if '--minutes' in sys.argv else 150
    t0 = time.time(); left = lambda: minutes * 60 - (time.time() - t0)
    import datetime; tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    have = {str(r['id']) for r in json.load(open('data.json'))['rows']}
    leads = json.load(open('leads.json')) if os.path.exists('leads.json') else {}
    done_path = f'hist-done-{shard}.txt'
    done = set(open(done_path).read().split()) if os.path.exists(done_path) else set()
    stats = {'shard': shard, 'files': 0, 'apps': 0, 'lead_apps': 0, 'looked_up': 0, 'recent': 0, 'not_on_duo': 0, 'on_site': 0,
             'hits_newest': 0, 'hits_description': 0, 'from_search': 0, 'hist_todo': 0, 'hist_read': 0, 'hits_history': 0, 'hist_blocked': 0, 'slowed': 0, 'failed_lookups': 0,
             'stopped_early': False, 'published_live': 0, 'hist_left': 0}
    # 1) the app ids of this slice: Apple's lists, then leads (developers' other apps, announced apps)
    store, lead_ids = {}, set()
    files = []
    for ix in INDEXES: files += re.findall(r'<loc>([^<]+)</loc>', fetch(ix))
    for k, f in enumerate(files):
        if k % shards != shard: continue
        try: xml = gzip.decompress(fetch(f, binary=True)).decode('utf-8', 'replace')
        except OSError: continue
        stats['files'] += 1
        for cc, i in re.findall(r'<loc>https://apps\.apple\.com/(\w+)/app/[^<]*/id(\d+)</loc>', xml): store.setdefault(i, cc)
    for i in leads.get('apps', []):
        if int(i) % shards == shard: lead_ids.add(i); store.setdefault(i, 'us')
    for artist in leads.get('developers', []):
        if int(artist) % shards != shard or left() < minutes * 30: continue
        for i in developer_apps(artist, stats): lead_ids.add(i); store.setdefault(i, 'us')
        time.sleep(0.4)
    stats['apps'] = len(store); stats['lead_apps'] = len(lead_ids)
    # 2) look every app up (US store first, then the store Apple's list names, if it is one of the site's markets)
    ids = list(store); found = {}
    for k in range(0, len(ids), 200):
        for a in lookup('us', ids[k:k + 200], stats) or []: found[str(a['trackId'])] = ('us', a)
        time.sleep(0.4)
    rest = {}
    for i in ids:
        if i not in found and store[i] in d.MARKETS and store[i] != 'us': rest.setdefault(store[i], []).append(i)
    for cc, v in rest.items():
        for k in range(0, len(v), 200):
            for a in lookup(cc, v[k:k + 200], stats) or []: found[str(a['trackId'])] = (cc, a)
            time.sleep(0.4)
    # new Duo-specific apps found by searching (this slice's share of terms x markets)
    jobs = [(t, cc) for t in SEARCH_TERMS for cc in d.MARKETS]
    for k, (t, cc) in enumerate(jobs):
        if k % shards != shard: continue
        for a in search(t, cc, stats):
            i = str(a.get('trackId', ''))
            if i and i not in found: found[i] = (cc, a); stats['from_search'] += 1
        time.sleep(3.5)
    stats['looked_up'] = len(found)
    hits, todo = [], []
    live, flushed, last = [], [0], [time.time()]
    def flush(force=False):
        if not force and time.time() - last[0] < LIVE_EVERY: return
        new = hits[flushed[0]:]
        if new:
            live.extend(make_rows(new, found, stats)); flushed[0] = len(hits)
            if save_live(shard, live): stats['published_live'] = len(live)
        last[0] = time.time()
    for i, (cc, a) in found.items():
        if (a.get('currentVersionReleaseDate') or '')[:10] < d.EARLIEST: continue
        if max((a.get('currentVersionReleaseDate') or '')[:10], (a.get('releaseDate') or '')[:10]) > tomorrow: continue   # pre-order
        stats['recent'] += 1
        if 'iPhoneDuo' not in ''.join(a.get('supportedDevices') or ['iPhoneDuo']): stats['not_on_duo'] += 1; continue
        if i in have or i in d.EXCLUDE: stats['on_site'] += 1; continue
        name = a.get('trackName', '')
        rec = {'id': i, 'cc': cc, 'app': name, 'artist': str(a.get('artistId', ''))}
        if d.duo_hit(a.get('releaseNotes') or '', name):
            hits.append(dict(rec, version=a.get('version', ''), date=(a.get('currentVersionReleaseDate') or '')[:10],
                             note=d.snippet(a.get('releaseNotes') or ''), how='newest notes'))
            stats['hits_newest'] += 1
        elif (a.get('releaseDate') or '')[:10] >= d.EARLIEST and d.duo_hit(a.get('description') or '', name):
            # new app (first released since Sep 2026): its own App Store description mentions iPhone Duo
            hits.append(dict(rec, version=a.get('version', ''), date=(a.get('releaseDate') or '')[:10],
                             note=d.snippet(a.get('description') or ''), how='description'))
            stats['hits_description'] += 1
        elif i not in done:
            todo.append((i not in lead_ids, -(a.get('userRatingCount') or 0), rec))
    flush(force=True)   # finds from newest notes and descriptions go to the site right away
    # 3) version histories: leads first, then the most-rated apps, until the time is up or Apple pushes back
    todo.sort(key=lambda t: (t[0], t[1])); stats['hist_todo'] = len(todo)
    fails = [0]
    def read(t):
        rec = t[2]
        if left() < 120 or fails[0] >= 25: return rec, None
        code, h = page(rec['id'], rec['cc'])
        if code in ('403', '429', '503'):
            fails[0] += 1; time.sleep(30 * fails[0]); return rec, None
        fails[0] = 0
        return rec, h
    with ThreadPoolExecutor(HIST_THREADS) as ex:
        for rec, h in ex.map(read, todo):
            if h is None: continue
            stats['hist_read'] += 1; done.add(rec['id'])
            first = [v for v in h if v[1] >= d.EARLIEST and d.duo_hit(v[2], rec['app'])]
            if first:
                v = min(first, key=lambda v: v[1])
                hits.append(dict(rec, version=v[0], date=v[1], note=d.snippet(v[2]), how='version history'))
                stats['hits_history'] += 1
            flush()
    flush(force=True)
    if fails[0] >= 25: stats['hist_blocked'] = 1
    stats['stopped_early'] = stats['hist_read'] < len(todo)
    stats['hist_left'] = len(todo) - stats['hist_read']
    stats['hits'] = len(hits)
    stats['minutes'] = round((time.time() - t0) / 60, 1)
    open(done_path, 'w').write('\n'.join(sorted(done)))
    json.dump({'stats': stats, 'hits': hits}, open(out, 'w'), ensure_ascii=False)
    print(json.dumps(stats))

if __name__ == '__main__':
    main()

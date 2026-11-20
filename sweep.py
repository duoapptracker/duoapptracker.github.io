"""Daily sweep of the whole App Store for apps whose newest update notes mention iPhone Duo.

Why: the regular scan (duo_cloud.py) only sees about 34,000 chart apps. Apple publishes a list of every app
(apps.apple.com/sitemaps_apps_index_app_1.xml, about 1,600 files and 2.9 million apps). This script takes one
slice of those files, looks the apps up 200 at a time, and keeps an app only if:
  - its newest version is from 1 Sep 2026 or later (iPhone Duo did not exist before),
  - it can run on iPhone Duo ("iPhoneDuo" in Apple's supported devices),
  - it is not on the site already,
  - its newest update notes mention iPhone Duo (same rule as the scan: duo_hit).
Found apps are only leads: the merge step queues them in submissions.json, and the regular scan reads each one's
version history and adds it with its real date if the notes really mention iPhone Duo.

Usage: python3 sweep.py SHARD SHARDS OUT.json [--minutes 100]
"""
import gzip, json, os, re, subprocess, sys, time
import duo_cloud as d

INDEX = 'https://apps.apple.com/sitemaps_apps_index_app_1.xml'

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

def main():
    shard, shards, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    minutes = float(sys.argv[sys.argv.index('--minutes') + 1]) if '--minutes' in sys.argv else 100
    t0 = time.time()
    site = json.load(open('data.json'))
    have = {str(r['id']) for r in site['rows']}
    stats = {'shard': shard, 'files': 0, 'apps': 0, 'looked_up': 0, 'recent': 0, 'not_on_duo': 0, 'on_site': 0,
             'hits': 0, 'slowed': 0, 'failed_lookups': 0, 'stopped_early': False}
    files = re.findall(r'<loc>([^<]+)</loc>', fetch(INDEX))
    mine = [f for k, f in enumerate(files) if k % shards == shard]
    hits = []
    for f in mine:
        if (time.time() - t0) / 60 > minutes: stats['stopped_early'] = True; break
        raw = fetch(f, binary=True)
        try: xml = gzip.decompress(raw).decode('utf-8', 'replace')
        except OSError: continue
        stats['files'] += 1
        store = {}
        for cc, i in re.findall(r'<loc>https://apps\.apple\.com/(\w+)/app/[^<]*/id(\d+)</loc>', xml):
            store.setdefault(i, cc)
        ids = list(store); stats['apps'] += len(ids)
        found = {}
        for k in range(0, len(ids), 200):
            for a in lookup('us', ids[k:k + 200], stats) or []: found[str(a['trackId'])] = ('us', a)
            time.sleep(0.4)
        # apps not sold in the US: ask the store the list names for them, if it is one of the site's markets
        rest = {}
        for i in ids:
            if i not in found and store[i] in d.MARKETS and store[i] != 'us': rest.setdefault(store[i], []).append(i)
        for cc, v in rest.items():
            for k in range(0, len(v), 200):
                for a in lookup(cc, v[k:k + 200], stats) or []: found[str(a['trackId'])] = (cc, a)
                time.sleep(0.4)
        stats['looked_up'] += len(found)
        for i, (cc, a) in found.items():
            if (a.get('currentVersionReleaseDate') or '')[:10] < d.EARLIEST: continue
            stats['recent'] += 1
            if 'iPhoneDuo' not in ''.join(a.get('supportedDevices') or ['iPhoneDuo']): stats['not_on_duo'] += 1; continue
            if i in have or i in d.EXCLUDE: stats['on_site'] += 1; continue
            if d.duo_hit(a.get('releaseNotes') or '', a.get('trackName', '')):
                hits.append({'id': i, 'cc': cc, 'app': a.get('trackName', ''), 'version': a.get('version', ''),
                             'date': (a.get('currentVersionReleaseDate') or '')[:10], 'note': d.snippet(a.get('releaseNotes') or '')})
                stats['hits'] += 1
    stats['minutes'] = round((time.time() - t0) / 60, 1)
    stats['files_total'] = len(mine)
    json.dump({'stats': stats, 'hits': hits}, open(out, 'w'), ensure_ascii=False)
    print(json.dumps(stats))

if __name__ == '__main__':
    main()

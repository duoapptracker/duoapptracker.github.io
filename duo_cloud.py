#!/usr/bin/env python3
"""Refresh of the iPhone Duo apps board, in one file. Works in time slices so it can be run again and again.
Usage: python3 duo_cloud.py PREVIOUS_board_rows.json NEW_board_rows.json [--slice SECONDS] [--hist-minutes MINUTES] [--site]
Each run works for at most --slice seconds (default 480), saves its progress in duo_state.json beside the output,
and prints CONTINUE (run the same command again) or DONE with a summary (the output file is written).
What it does: reads the App Store charts of nine markets (India, US, UK, UAE, Singapore, Australia, Canada, Germany,
Japan; overall and 24 categories everywhere, plus 19 game types in India, the US and the UK), notes which markets'
charts each app is in,
keeps the apps available on the India store, and for each one not yet on the board reads its version history
to find the first version whose notes mention iPhone Duo. Apps are never removed from the board.
Reads only Apple's public feeds and store pages; writes only the output file and duo_state.json."""
import json, re, subprocess, datetime, os, sys, time, base64
from concurrent.futures import ThreadPoolExecutor
MARKETS = {'in': 'India', 'us': 'United States', 'gb': 'United Kingdom', 'ae': 'UAE', 'sg': 'Singapore', 'au': 'Australia', 'ca': 'Canada', 'de': 'Germany', 'jp': 'Japan'}
FULL = ['in', 'us', 'gb']   # these markets also get the 19 game-type charts
GENRES = [0,6000,6001,6002,6003,6004,6005,6006,6007,6008,6009,6010,6011,6012,6013,6014,6015,6016,6017,6018,6020,6023,6024,6026,6027] + list(range(7001, 7020))
CHARTS = ['topfreeapplications','toppaidapplications','topgrossingapplications']
FEEDS = [(c, g, ch) for c in MARKETS for g in GENRES if c in FULL or g < 7000 for ch in CHARTS]
EARLIEST = '2026-09-01'   # iPhone Duo was announced in September 2026; a version older than this cannot mention it
PAT = re.compile(r'iphone\s*duo|\bduo\b[^.\n]{0,40}(support|display|screen|layout|optimi[sz]|fold)|(support|optimi[sz]\w*|ready|built|designed|compatib\w*)[^.\n]{0,40}\bduo\b|fold(able|ing)\s+(iphone|display|screen)', re.I)
SITE = '--site' in sys.argv   # for the public website: no embedded icon images (the page loads icons from Apple), one app per line
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15'

def curl(url, binary=False, agent=None):
    cmd = ['curl', '-sL', '--compressed', '-m', '60'] + (['-A', agent] if agent else []) + [url]
    r = subprocess.run(cmd, capture_output=True)
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace')

def get(url):
    for _ in range(3):
        try: return json.loads(curl(url))
        except ValueError: time.sleep(2)
    return None

def one_line(text):
    line = next((l.strip() for l in (text or '').split('\n') if l.strip()), '')
    m = re.search(r'(?<=[.!?。])\s', line)
    if m and m.start() >= 30: line = line[:m.start()]
    return line if len(line) <= 150 else line[:147].rsplit(' ', 1)[0] + '…'

def snippet(text):
    m = PAT.search(text)
    return ' '.join(text[max(0, m.start() - 80):m.end() + 120].split())[:260]

def icon(art):
    if not art: return ''
    b = curl(art.rsplit('/', 1)[0] + '/64x64bb.jpg', binary=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(b).decode() if b[:2] == b'\xff\xd8' else ''

def history(url):
    """[(version, 'YYYY-MM-DD', notes)] from the app's India store page, or [] if it could not be read."""
    html = curl(url, agent=UA)
    i = html.find('"page":"versionHistory","pageData":')
    if i < 0: return []
    try: data, _ = json.JSONDecoder().raw_decode(html, html.index('{', i + 30))
    except ValueError: return []
    out = []
    for shelf in data.get('shelves', []):
        for it in shelf.get('items', []):
            try: d = datetime.datetime.strptime(' '.join((it.get('secondarySubtitle') or '').split()[:4]), '%a %b %d %Y').date().isoformat()
            except ValueError: continue
            out.append((it.get('primarySubtitle') or '', d, it.get('text') or ''))
    return out

def show(st, path, done=False):
    """Write a small self-refreshing progress page beside the output file (at most every 3 seconds)."""
    if not done and time.time() - show.last < 3: return
    show.last = time.time()
    esc = lambda t: str(t).replace('&', '&amp;').replace('<', '&lt;')
    order = ['charts', 'lookup', 'history', 'write']
    parts = [('Read the charts', 'charts', st['feed'], len(FEEDS), 'charts'),
             ('Look up each app on the India store', 'lookup', min(st['batch'] * 100, len(st['ids'])), len(st['ids']), 'apps'),
             ('Read version histories', 'history', st['qpos'], len(st['queue'] or []), 'apps')]
    now = 3 if done else order.index(st['stage'])
    bars = ''
    for i, (label, key, n, total, unit) in enumerate(parts):
        pct = 100 if i < now else (0 if i > now or not total else 100 * n / total)
        text = 'done' if i < now else ('waiting' if i > now else '%s of %s %s' % (format(n, ','), format(total, ','), unit))
        bars += '<div class="s"><div class="l"><b>%d. %s</b><span>%s</span></div><div class="t"><div class="f" style="width:%.1f%%"></div></div></div>' % (i + 1, label, text, pct)
    names = [st['rows'][t]['app'] for t in st['new'][-12:]][::-1]
    page = ('<!doctype html><meta charset="utf-8">' + ('' if done else '<meta http-equiv="refresh" content="4">') + '<title>Duo scan progress</title>'
      '<style>body{background:#1a1b26;color:#c0caf5;font:16px -apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 20px}h1{font-size:22px;margin:0 0 4px}'
      '.m{color:#7982a9;margin:0 0 28px}.s{margin:0 0 22px}.l{display:flex;justify-content:space-between;margin-bottom:8px}.l span{color:#7982a9;font-variant-numeric:tabular-nums}'
      '.t{height:12px;background:#292e42;border-radius:6px;overflow:hidden}.f{height:100%;background:#7aa2f7;border-radius:6px}'
      '.k{display:flex;gap:28px;margin:30px 0 18px}.k div{font-size:13px;color:#7982a9}.k b{display:block;font-size:28px;color:#9ece6a;font-weight:500}li{margin:4px 0}ul{padding-left:20px;color:#a9b1d6}</style>'
      '<h1>iPhone Duo scan ' + ('finished' if done else 'in progress') + '</h1><p class="m">Updated ' + time.strftime('%H:%M:%S') + ('' if done else ' · this page refreshes by itself') + '</p>' + bars +
      '<div class="k"><div><b>%s</b>apps on the board</div><div><b>%s</b>new apps found</div><div><b>%s</b>history pages read</div></div>' % (format(len(st['rows']), ','), format(len(st['new']), ','), format(st['pages_read'], ','))
      + ('<p class="m">Latest finds</p><ul>' + ''.join('<li>%s</li>' % esc(n) for n in names) + '</ul>' if names else ''))
    tmp = path + '.tmp'
    open(tmp, 'w').write(page); os.replace(tmp, path)
show.last = 0

def main():
    args = sys.argv[1:]
    opt = lambda name, default: float(args[args.index(name) + 1]) if name in args else default
    prev_path, out_path = args[0], args[1]
    slice_s, hist_s = opt('--slice', 480), opt('--hist-minutes', 20) * 60
    t0 = time.time()
    left = lambda: slice_s - (time.time() - t0)
    state_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'duo_state.json')
    today = datetime.datetime.utcnow().date().isoformat()
    if os.path.exists(state_path):
        st = json.load(open(state_path))
    else:
        prev = json.load(open(prev_path))
        st = {'stage': 'charts', 'feed': 0, 'ids': [], 'india_ids': 0, 'batch': 0, 'seen': 0,
              'rows': {str(r['id']): r for r in (prev['rows'] if isinstance(prev, dict) else prev)},
              'checked': prev.get('checked', {}) if isinstance(prev, dict) else {}, 'cand': {}, 'queue': None, 'qpos': 0,
              'hist_spent': 0, 'new': [], 'changed': 0, 'pages_read': 0, 'mk': {}}
        st['before'] = len(st['rows'])
    rows, checked, cand = st['rows'], st['checked'], st['cand']
    page_path = os.path.join(os.path.dirname(state_path), 'duo_progress.html')
    saved = [time.time()]
    def tick():
        show(st, page_path)
        if time.time() - saved[0] > 120:   # checkpoint, so an interrupted run loses little
            json.dump(st, open(state_path + '.tmp', 'w'), ensure_ascii=False); os.replace(state_path + '.tmp', state_path); saved[0] = time.time()
    def pause():
        json.dump(st, open(state_path, 'w'), ensure_ascii=False)
        print('CONTINUE stage=%s progress=%s' % (st['stage'], {'charts': '%d/%d feeds' % (st['feed'], len(FEEDS)),
              'lookup': '%d/%d apps' % (st['batch'] * 100, len(st['ids'])), 'history': '%d/%d pages' % (st['qpos'], len(st['queue'] or []))}.get(st['stage'], '')))
        sys.exit(0)

    if st['stage'] == 'charts':
        while st['feed'] < len(FEEDS):
            if left() < 20: pause()
            c, g, ch = FEEDS[st['feed']]
            d = get(f'https://itunes.apple.com/{c}/rss/{ch}/limit=200/' + (f'genre={g}/' if g else '') + 'json')
            e = (d or {}).get('feed', {}).get('entry', [])
            got = [x['id']['attributes']['im:id'] for x in ([e] if isinstance(e, dict) else e)]
            st['ids'] += got
            for i in got:   # remember which markets' charts list this app
                m = st['mk'].setdefault(i, [])
                if c not in m: m.append(c)
            st['feed'] += 1; tick()
            if c == 'in': st['india_ids'] = len(set(st['ids']))
        if st['india_ids'] < 3000:
            sys.exit(f"STOP: only {st['india_ids']} apps read from the India charts; Apple feeds unreachable or changed. Nothing written.")
        st['ids'] = list(dict.fromkeys(st['ids'] + list(rows)))
        st['stage'] = 'lookup'

    if st['stage'] == 'lookup':
        ids = st['ids']
        while st['batch'] * 100 < len(ids):
            if left() < 30: pause()
            k = st['batch'] * 100
            d = get('https://itunes.apple.com/lookup?country=in&id=' + ','.join(ids[k:k + 100]))
            for a in (d or {}).get('results', []):
                st['seen'] += 1
                tid = str(a['trackId']); notes = a.get('releaseNotes') or ''
                latest = {'app': a['trackName'], 'developer': a.get('artistName', ''), 'category': a.get('primaryGenreName', ''),
                          'version': a.get('version', ''), 'updated': a.get('currentVersionReleaseDate', '')[:10], 'price': a.get('formattedPrice', ''),
                          'rating': round(a.get('averageUserRating', 0), 1), 'ratings': a.get('userRatingCount', 0),
                          'url': a.get('trackViewUrl', '').split('?')[0], 'art': a.get('artworkUrl100', ''), 'desc': one_line(a.get('description', '')), 'min_ios': a.get('minimumOsVersion', '')}
                latest['markets'] = ','.join(st['mk'].get(tid, [])) or rows.get(tid, {}).get('markets', '')
                if tid in rows:
                    r = rows[tid]
                    if r.get('version') != latest['version']: st['changed'] += 1
                    r.update(latest)
                    if not SITE and not r.get('icon'): r['icon'] = icon(a.get('artworkUrl100', ''))
                elif latest['updated'] >= EARLIEST and checked.get(tid) != latest['version']:
                    # not on the board, recent enough, and this version's history has not been read yet
                    cand[tid] = dict(latest, now=snippet(notes) if PAT.search(notes) else '')
            st['batch'] += 1; tick()
        # apps that are not sold in India return nothing, so compare with the India chart size only
        if st['seen'] < 0.8 * st['india_ids']:
            sys.exit(f"STOP: Apple answered for only {st['seen']} apps. Nothing written.")
        # read first: board apps still waiting for a history check, then apps whose current notes mention Duo, then the most rated
        st['queue'] = [t for t, r in rows.items() if r.get('hist_ok') is False] + \
                      sorted(cand, key=lambda t: (not cand[t]['now'], -cand[t]['ratings']))
        st['stage'] = 'history'

    if st['stage'] == 'history':
        q = st['queue']
        def read(tid):
            return tid, history((rows.get(tid) or cand[tid])['url'])
        def add(tid, c, ver, d, note, ok):
            rows[tid] = {k: c[k] for k in c if k != 'now'}
            rows[tid].update(id=tid, duo_date=d, duo_version=ver, note=note, first_seen=today, hist_ok=ok)
            if not SITE: rows[tid]['icon'] = icon(c['art'])
            st['new'].append(tid)
        while st['qpos'] < len(q):
            # the history budget applies only to apps that do not mention Duo in their current notes
            head = q[st['qpos']]
            urgent = head in rows or bool(cand.get(head, {}).get('now'))
            if not urgent and st['hist_spent'] >= hist_s: break
            if left() < 75: pause()
            chunk = q[st['qpos']:st['qpos'] + 32]; t1 = time.time(); got = 0
            with ThreadPoolExecutor(4) as ex:
                for tid, h in ex.map(read, chunk):
                    hits = [x for x in h if x[1] >= EARLIEST and PAT.search(x[2])]   # older mentions are other products called Duo
                    first = min(hits, key=lambda x: x[1]) if hits else None
                    if h: got += 1; st['pages_read'] += 1
                    if tid in rows:
                        r = rows[tid]
                        if h: r['hist_ok'] = True
                        if first and first[1] <= r['duo_date']: r.update(duo_version=first[0], duo_date=first[1], note=snippet(first[2]))
                        continue
                    c = cand[tid]
                    if h: checked[tid] = c['version']
                    if first: add(tid, c, first[0], first[1], snippet(first[2]), True)
                    elif c['now']: add(tid, c, c['version'], c['updated'], c['now'], bool(h))
            st['qpos'] += len(chunk); st['hist_spent'] += time.time() - t1; tick()
            if got < len(chunk) / 2: time.sleep(20)   # Apple is slowing us down; pages not read stay for the next run
        st['stage'] = 'write'

    out = sorted(rows.values(), key=lambda r: (r['duo_date'], r['ratings']), reverse=True)
    assert len(out) >= st['before']
    pool = set(st['ids'])
    meta = [{'label': 'duo_cloud.py', 'value': open(os.path.abspath(__file__)).read(), 'type': 'code', 'lang': 'python'},
            {'label': 'Input', 'value': 'App Store top free, top paid and top grossing charts of ' + ', '.join(MARKETS.values()) + ' (overall and 24 categories; plus 19 game types in India, the US and the UK), limited to apps on the India store, plus every app already on the board; read from Apple public feeds and store pages'}]
    keep = {k: v for k, v in checked.items() if k in pool and k not in rows}
    if SITE:
        for r in out: r.pop('icon', None)
        with open(out_path, 'w') as f:   # one app per line keeps daily changes small in version control
            f.write('{"updated": %s,\n"rows": [\n' % json.dumps(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')))
            f.write(',\n'.join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in out))
            f.write('\n],\n"checked": %s}\n' % json.dumps(keep, sort_keys=True))
    else:
        json.dump({'rows': out, 'meta': meta, 'checked': keep}, open(out_path, 'w'), ensure_ascii=False)
    st['stage'] = 'write'; show(st, page_path, done=True)
    os.remove(state_path) if os.path.exists(state_path) else None
    print('DONE ' + json.dumps({'date': today, 'apps_checked': st['seen'], 'total_apps': len(out), 'new_apps': [rows[t]['app'] for t in st['new']],
          'apps_with_a_newer_version': st['changed'], 'history_pages_read': st['pages_read'],
          'history_pages_still_waiting': max(0, len(st['queue']) - st['qpos']), 'bytes': os.path.getsize(out_path)}, ensure_ascii=False))

if __name__ == '__main__':
    main()

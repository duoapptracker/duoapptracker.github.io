"""Add the finds saved by the check's slices (branch 'live', files live/<slice>.json) to the site's list (data.json).

Rows are complete (details, date, note, ratings per market), so nothing is read again; apps already on the
site, blocked apps and pre-orders are skipped. data.json keeps its one-app-per-line format.
Usage: python3 publish_live.py            (prints how many apps were added)
"""
import base64, datetime, json, os, subprocess, sys
import duo_cloud as d

def live_rows(repo):
    out = subprocess.run(['gh', 'api', f'repos/{repo}/contents/live?ref=live', '--jq', '.[].path'], capture_output=True, text=True).stdout.split()
    rows = []
    for path in out:
        raw = subprocess.run(['gh', 'api', f'repos/{repo}/contents/{path}?ref=live', '-H', 'Accept: application/vnd.github.raw'],
                             capture_output=True).stdout
        try: rows += json.loads(raw.decode('utf-8', 'replace')).get('rows', [])
        except ValueError: pass
    return rows

def main():
    repo = os.environ['GITHUB_REPOSITORY']
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    txt = open('data.json').read()
    have = {str(r['id']) for r in json.loads(txt)['rows']}
    new, seen = [], set()
    for r in live_rows(repo):
        i = str(r.get('id', ''))
        if not i or i in have or i in seen or i in d.EXCLUDE: continue
        if max(str(r.get('updated', '')), str(r.get('released', ''))) > tomorrow: continue   # pre-order
        if not d.duo_hit(r.get('note', ''), r.get('app', '')): continue                       # evidence must pass today's rule
        seen.add(i); new.append(r)
    if new:
        lines = txt.split('\n'); k = lines.index('],')
        if not lines[k - 1].endswith(','): lines[k - 1] += ','
        add = [json.dumps(r, ensure_ascii=False, sort_keys=True) + ',' for r in new]
        add[-1] = add[-1][:-1]
        lines[k:k] = add
        out = '\n'.join(lines); json.loads(out)
        open('data.json', 'w').write(out)
    print(len(new))

if __name__ == '__main__':
    main()

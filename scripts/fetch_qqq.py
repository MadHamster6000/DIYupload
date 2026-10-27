#!/usr/bin/env python3
"""Snapshot public QQQ market data (Yahoo Finance chart API) into data/qqq/ — market data only, never trade data.
  data/qqq/1d.json            daily bars, all available history   [["YYYY-MM-DD",o,h,l,c,v],...]
  data/qqq/YYYY-MM-DD.json    per trading day {"d":..., "m1":[...], "m15":[...], "h1":[...]}
                              bar = [minute_of_day_ET, o, h, l, c, v]; sessions 04:00-20:00 ET (pre, regular, post)
  data/qqq/index.json         coverage index
Yahoo free limits (tested): 1m ≈ last 30 days (7-day requests), 5m/15m ≈ 60 days, 60m ≈ 730 days, daily = full.
Existing snapshots are never deleted; a timeframe is only replaced by a fetch with more bars."""
import json, os, time, urllib.request, datetime, zoneinfo
ET = zoneinfo.ZoneInfo('America/New_York'); SYM = 'QQQ'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', SYM.lower())
def fetch(interval, p1, p2, pre=True):
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{SYM}?interval={interval}&period1={int(p1)}&period2={int(p2)}'
         f'&includePrePost={"true" if pre else "false"}')
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
            res = r['chart']['result']; break
        except Exception as e:
            print('retry', interval, e); time.sleep(3); res = None
    if not res: return []
    q = res[0]['indicators']['quote'][0]; out = []
    for i, t in enumerate(res[0].get('timestamp') or []):
        o, h, l, c, v = (q[k][i] for k in ('open', 'high', 'low', 'close', 'volume'))
        if None in (o, h, l, c): continue
        out.append((t, round(o, 2), round(h, 2), round(l, 2), round(c, 2), int(v or 0)))
    return out
def by_day(bars):
    days = {}
    for t, o, h, l, c, v in bars:
        dt = datetime.datetime.fromtimestamp(t, ET); days.setdefault(dt.date().isoformat(), []).append([dt.hour * 60 + dt.minute, o, h, l, c, v])
    return days
def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f: json.dump(obj, f, separators=(',', ':'))
def main():
    now = time.time(); os.makedirs(OUT, exist_ok=True)
    # daily
    p = os.path.join(OUT, '1d.json'); daily = {}
    if os.path.exists(p): daily = {b[0]: b for b in json.load(open(p))}
    for t, o, h, l, c, v in fetch('1d', now - 25 * 365 * 86400, now, pre=False):
        d = datetime.datetime.fromtimestamp(t, ET).date().isoformat(); daily[d] = [d, o, h, l, c, v]
    save(p, sorted(daily.values()))
    # intraday
    got = {'m1': {}, 'm15': {}, 'h1': {}}
    for k in range(5):  # 1m: 7-day chunks back ~30 days
        e = now - k * 7 * 86400; s = e - 7 * 86400
        for d, b in by_day(fetch('1m', s, e)).items(): got['m1'].setdefault(d, []).extend(b)
    got['m15'] = by_day(fetch('15m', now - 59 * 86400, now))
    got['h1'] = by_day(fetch('60m', now - 729 * 86400, now))
    changed = 0
    for tf, days in got.items():
        for d, bars in days.items():
            bars = sorted({b[0]: b for b in bars}.values())
            fp = os.path.join(OUT, d + '.json'); snap = json.load(open(fp)) if os.path.exists(fp) else {'d': d}
            if len(bars) > len(snap.get(tf, [])): snap[tf] = bars; save(fp, snap); changed += 1
    idx = {}
    for f in sorted(os.listdir(OUT)):
        if len(f) == 15 and f[4] == '-':
            s = json.load(open(os.path.join(OUT, f))); idx[f[:10]] = ''.join(k for k, tf in (('1', 'm1'), ('f', 'm15'), ('h', 'h1')) if s.get(tf))
    dk = sorted(daily)
    save(os.path.join(OUT, 'index.json'), {'symbol': SYM, 'updated': datetime.datetime.now(ET).isoformat(timespec='minutes'), 'daily': [dk[0], dk[-1]],
         'days': idx, 'legend': '1=1m f=15m h=1h', 'source': 'Yahoo Finance chart API (public market data, delayed)'})
    print('daily', len(dk), dk[0], '→', dk[-1], '| day files updated', changed,
          '| 1m days', sum('1' in v for v in idx.values()), '| 15m days', sum('f' in v for v in idx.values()), '| 1h days', sum('h' in v for v in idx.values()))
    # Bump site last-updated stamp when QQQ data changes
    if changed:
        now_et = datetime.datetime.now(ET)
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        ampm = 'AM' if now_et.hour < 12 else 'PM'
        h12 = now_et.hour % 12 or 12
        stamp = {
            'iso': now_et.isoformat(timespec='minutes'),
            'label': f'Updated {months[now_et.month-1]} {now_et.day}, {now_et.year} · {h12}:{now_et.minute:02d} {ampm} ET',
            'source': 'qqq-data',
            'date': now_et.date().isoformat(),
        }
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        save(os.path.join(root, 'data', 'updated.json'), stamp)
        print('updated', stamp['label'])
if __name__ == '__main__': main()

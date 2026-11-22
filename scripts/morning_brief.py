#!/usr/bin/env python3
"""Morning Brief: QQQ/SPY 0DTE option walls, macro + earnings calendar, gamma squeeze scanner.
Free public data only (options: CBOE delayed -> Nasdaq -> Yahoo; prices Yahoo via yfinance, ForexFactory weekly JSON, Nasdaq earnings API). No secrets.
Writes data/brief/latest.json and data/brief/YYYY-MM-DD.json. OI is prior-day; prices delayed."""
import json, os, sys, time, math, datetime, zoneinfo, urllib.request, traceback, socket
import yfinance as yf
socket.setdefaulttimeout(30)
ET = zoneinfo.ZoneInfo('America/New_York')
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'brief')
T0 = time.time(); HARD = 10 * 60; BUDGET = 8 * 60  # scanner cap; whole run should stay under ~10 min
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
      'Accept': 'application/json, text/plain, */*'}
errors = []
BACKOFF = (5, 10, 20, 30)
def is_forbidden(e):
    s = f'{getattr(e, "code", "")} {e}'.lower()
    return '403' in s or 'forbidden' in s or 'http error 401' in s
def retry(fn, tries=5, backoff=BACKOFF, what='fetch'):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f'{what} try {i + 1}/{tries}: {e}')
            if is_forbidden(e): raise
            if i < tries - 1: time.sleep(backoff[min(i, len(backoff) - 1)])
    raise last
def get_json(u, h=UA, tries=3):
    return retry(lambda: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=30)), tries=tries, what=u.split('/')[2] if '://' in u else 'get_json')
def num(x, d=0.0):
    try:
        x = float(x); return d if math.isnan(x) else x
    except Exception: return d
def ncdf_pdf(x): return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)
def bs_gamma(S, K, T, iv, r=0.04):
    if S <= 0 or K <= 0 or T <= 0 or iv <= 0: return 0.0
    d1 = (math.log(S / K) + (r + iv * iv / 2) * T) / (iv * math.sqrt(T))
    return ncdf_pdf(d1) / (S * iv * math.sqrt(T))

def ncdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs_straddle(S, K, T, iv, r=0.04):
    if S <= 0 or K <= 0 or T <= 0 or iv <= 0: return None
    v = iv * math.sqrt(T); d1 = (math.log(S / K) + (r + iv * iv / 2) * T) / v; d2 = d1 - v
    c = S * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
    return c + (c - S + K * math.exp(-r * T))  # call + put via parity

# ---------- Straddle scaling ----------
# A pre-market chain quotes the ATM straddle at the last print (usually the prior session's close),
# so it carries extra time (overnight/weekend) and the old spot's moneyness. Same-day estimate:
#  (1) preferred: reprice with Black-Scholes at the CURRENT spot, ATM strike, quoted IV and the time
#      left in today's session, T = session_hours_left / (252 * 6.5) years (trading-time).
#  (2) fallback (no usable IV): st_est = st_quote * sqrt(days_remaining_today / days_at_quote), where
#      'days' are variance-days: each regular session = 1.0, each overnight/weekend gap = GAP_W.
#      e.g. Fri-close quote for a Mon 0DTE: days_at_quote = 1 + 0.3 = 1.3; pre-market Mon = 1.0 -> x0.877.
GAP_W = 0.3  # assumed share of a day's variance realised across a close->open gap (approximation)
def session_days_left(now, expdt):
    o = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if now.date() != expdt.date(): return None
    if now <= o: return 1.0
    return max((expdt - now).total_seconds(), 0) / (6.5 * 3600)
def variance_days(t0, expdt):
    d, days = t0, 0.0
    o = t0.replace(hour=9, minute=30, second=0, microsecond=0); c = t0.replace(hour=16, minute=0, second=0, microsecond=0)
    if t0.weekday() < 5 and t0 < c: days += (c - max(t0, o)).total_seconds() / (6.5 * 3600)
    day = t0.date() + datetime.timedelta(days=1)
    while day <= expdt.date():
        if day.weekday() < 5: days += GAP_W + 1.0
        day += datetime.timedelta(days=1)
    return days
def scale_straddle(st, quote_ts, now, expdt, spot=None, k=None, iv=None):
    """Return (estimate, method) or (st, 'quote') when the quote is from today's session."""
    left = session_days_left(now, expdt)
    sess_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if quote_ts is None or left is None or quote_ts >= sess_open: return st, 'quote'
    if spot and k and iv and 0.05 < iv < 2:
        est = bs_straddle(spot, k, left / 252, iv)
        if est: return est, f'estimate: BS reprice spot {round(spot, 2)}, K {k}, IV {iv:.3f}, {left:.2f} session-days left'
    dq = variance_days(quote_ts, expdt)
    if dq <= 0: return st, 'quote'
    return st * math.sqrt(left / dq), f'estimate: quote x sqrt({left:.2f}/{dq:.2f}) variance-days'

# ---------- Data-quality checks ----------
# A partial Yahoo chain can look real but shift every level. Those cases are retried / de-prioritised.
# A far or missing gamma flip is NOT a hard fail: the plan is built from other real levels instead.
OI_DROP_MAX = 0.50        # total OI down more than 50% vs the previous same-expiry run
PCR_MAX = 3.0             # put/call OI ratio above 3 (often a truncated chain)
FLIP_WARN_STRADDLES = 1.0  # > 1 straddle: warning, flip still used if within the max
FLIP_MAX_STRADDLES = 2.0  # > 2 straddles: flip is treated as unreliable; bias comes from other real data
def chain_fatal(w):
    """True gaps: cannot publish a plan from this chain. Never invent a spot or walls."""
    if not w: return ['no walls']
    if not w.get('spot'): return ['no spot']
    tot = (w.get('total_call_oi') or 0) + (w.get('total_put_oi') or 0)
    if tot <= 0: return ['no option OI on chain']
    if not any(w.get(k) for k in ('put_wall_oi', 'call_wall_oi', 'put_wall_gamma', 'call_wall_gamma')):
        return ['no OI/gamma walls']
    return []
def chain_soft(w, prev=None):
    """Suspicious-but-usable chain: try the next source first, accept if nothing cleaner arrives."""
    if not w: return []
    soft = []
    tot = (w.get('total_call_oi') or 0) + (w.get('total_put_oi') or 0)
    same = prev and prev.get('expiry') == w.get('expiry')
    ptot = ((prev.get('total_call_oi') or 0) + (prev.get('total_put_oi') or 0)) if same else 0
    if ptot and tot < (1 - OI_DROP_MAX) * ptot: soft.append(f'total OI {tot:,} is down {100 * (1 - tot / ptot):.0f}% vs last run ({ptot:,})')
    if (w.get('pcr_oi') or 0) > PCR_MAX: soft.append(f"put/call OI ratio {w['pcr_oi']} > {PCR_MAX}")
    return soft
def quality_warnings(w):
    """Soft checks: shown in the brief, plan still emitted."""
    out = []
    st, f, spot = (w or {}).get('straddle'), (w or {}).get('gamma_flip'), (w or {}).get('spot')
    if st and f is not None and spot is not None and abs(f - spot) > FLIP_WARN_STRADDLES * st:
        out.append(f"WARNING: gamma flip {f} is {abs(f - spot) / st:.1f}x straddle from spot {spot} (straddle {st}); flip-based bias less reliable" +
                   ('' if abs(f - spot) <= FLIP_MAX_STRADDLES * st else f' — flip ignored for bias (>{FLIP_MAX_STRADDLES:g}x)'))
    return out
def prev_walls(sym):
    try:
        b = json.load(open(os.path.join(OUT, 'latest.json')))
        return next((w for w in b.get('walls', []) if w.get('sym') == sym), None)
    except Exception: return None
def fetch_checked(sym, prev, tries=5, backoff=BACKOFF):
    """walls() with retries (CBOE -> Nasdaq -> Yahoo). First clean source wins.
    Far/missing flip is allowed through. Returns (walls, fatal-reasons-or-[]).
    A 403/forbidden on a source skips the rest of that source's retries."""
    usable, allbad, soft_keep = None, [], None
    for src in SOURCES:
        last_bad = []
        for i in range(tries):
            try:
                _TCACHE.pop((sym, src), None)
                w1 = walls(sym, 0, src)
                fatal = chain_fatal(w1)
                if not fatal:
                    soft = chain_soft(w1, prev)
                    if not soft:
                        return w1, []
                    usable = w1; soft_keep = soft
                    print(f'{sym} [{src}] usable with warnings:', soft)
                    last_bad = soft
                    break  # don't hammer a stable soft-issue chain
                last_bad = fatal
            except Exception as e:
                last_bad = [f'walls {sym}: {e}']
                if is_forbidden(e):
                    print(f'{sym} [{src}] skipped (forbidden):', e)
                    break
            print(f'{sym} [{src}] try {i + 1}/{tries}:', last_bad)
            if i < tries - 1: time.sleep(backoff[min(i, len(backoff) - 1)])
        allbad.append(f"{SRC_LABEL[src]}: " + '; '.join(last_bad or ['failed']))
    if usable and not chain_fatal(usable):
        return usable, []
    return usable, allbad

def label_walls(w):
    if not w: return w
    w['labels'] = {'gamma_call_wall': f"gamma call wall {w.get('call_wall_gamma')}", 'oi_call_wall': f"OI call wall {w.get('call_wall_oi')}",
                   'gamma_put_wall': f"gamma put wall {w.get('put_wall_gamma')}", 'oi_put_wall': f"OI put wall {w.get('put_wall_oi')}",
                   'use': 'gamma walls = wall entry; OI walls = break trigger'}
    return w

# ---------- Options chain sources: CBOE (primary) -> Nasdaq (backup) -> Yahoo (last) ----------
import re, subprocess
import pandas as pd
SRC_LABEL = {'cboe': 'CBOE delayed 15-min', 'nasdaq': 'Nasdaq.com delayed', 'yahoo': 'Yahoo Finance (yfinance)'}
SOURCES = ('cboe', 'nasdaq', 'yahoo')
def curl_json(u):
    r = subprocess.run(['curl', '-sL', '--fail', '--max-time', '30', '-A', UA['User-Agent'], '-H', 'Accept: application/json',
                        '-w', '\nHTTP_CODE:%{http_code}', u], capture_output=True)
    raw = (r.stdout or b'').decode('utf-8', 'replace')
    err = (r.stderr or b'').decode('utf-8', 'replace')[:200]
    code, body = None, raw
    if 'HTTP_CODE:' in raw:
        body, _, tail = raw.rpartition('HTTP_CODE:')
        code = tail.strip()
    if r.returncode != 0:
        raise RuntimeError(f'curl {u} exit {r.returncode} HTTP {code or "?"} {err}'.strip())
    return json.loads(body)
class _Chain:
    def __init__(s, c, p): s.calls, s.puts = pd.DataFrame(c), pd.DataFrame(p)
class _SrcTicker:
    """yfinance-like ticker: spot history from Yahoo, chain from another source."""
    def __init__(s, sym, by, last):
        s.r = yf.Ticker(sym); s.by = by; s.fast_info = {'lastPrice': last}
        today = datetime.datetime.now(ET).date().isoformat()
        s.options = sorted(e for e in by if e >= today)
    def history(s, **k): return s.r.history(**k)
    def option_chain(s, e): return _Chain(s.by[e]['C'], s.by[e]['P'])
def _cboe(sym):
    d = curl_json(f'https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json')['data']
    rx = re.compile(sym + r'(\d{6})([CP])(\d{8})'); by = {}
    for o in d['options']:
        m = rx.match(o['option'])
        if not m: continue
        e = '20' + m[1][:2] + '-' + m[1][2:4] + '-' + m[1][4:]
        ts = o.get('last_trade_time')
        by.setdefault(e, {'C': [], 'P': []})[m[2]].append({'strike': int(m[3]) / 1000, 'openInterest': o.get('open_interest'), 'volume': o.get('volume'),
            'impliedVolatility': o.get('iv'), 'bid': o.get('bid'), 'ask': o.get('ask'), 'lastPrice': o.get('last_trade_price'),
            'lastTradeDate': pd.Timestamp(ts).tz_localize(ET) if ts else None})
    return _SrcTicker(sym, by, d.get('current_price'))
_MON = {m: i + 1 for i, m in enumerate(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])}
def _nasdaq(sym):
    t0 = datetime.datetime.now(ET).date(); t1 = t0 + datetime.timedelta(days=7)
    d = curl_json(f'https://api.nasdaq.com/api/quote/{sym}/option-chain?assetclass=etf&fromdate={t0}&todate={t1}&limit=5000')['data']
    rx = re.compile(r'---(\d{6})c(\d{8})'); by = {}
    f = lambda x: num(str(x).replace(',', '')) if x not in (None, '--', '') else None
    for r in d['table']['rows']:
        m = rx.search(r.get('drillDownURL') or '')
        if not m or r.get('strike') is None: continue
        e = '20' + m[1][:2] + '-' + m[1][2:4] + '-' + m[1][4:]; k = f(r['strike'])
        g = by.setdefault(e, {'C': [], 'P': []})
        for side, pre in (('C', 'c_'), ('P', 'p_')):
            g[side].append({'strike': k, 'openInterest': f(r.get(pre + 'Openinterest')) or 0, 'volume': f(r.get(pre + 'Volume')) or 0,
                            'impliedVolatility': 0, 'bid': f(r.get(pre + 'Bid')) or 0, 'ask': f(r.get(pre + 'Ask')) or 0,
                            'lastPrice': f(r.get(pre + 'Last')) or 0, 'lastTradeDate': None})
    if not by: raise RuntimeError('nasdaq: empty chain')
    return _SrcTicker(sym, by, None)
_TCACHE = {}
def get_ticker(sym, src='yahoo'):
    if src == 'yahoo': return yf.Ticker(sym)
    k = (sym, src)
    if k not in _TCACHE: _TCACHE[k] = _cboe(sym) if src == 'cboe' else _nasdaq(sym)
    return _TCACHE[k]

# ---------- 1) Walls ----------
def attach_session_levels(res, hist):
    """Prior session OHLC, VWAP, and today's premarket high/low from real 1m bars. Omit a field if it is not in the bars."""
    if hist is None or getattr(hist, 'empty', True): return res
    h = hist.copy()
    if h.index.tz is None: h.index = h.index.tz_localize(ET)
    else: h.index = h.index.tz_convert(ET)
    idx = h.index
    rth = h[(idx.weekday < 5) & ((idx.hour > 9) | ((idx.hour == 9) & (idx.minute >= 30))) & (idx.hour < 16)]
    if rth.empty: return res
    now = datetime.datetime.now(ET); today = now.date()
    days = sorted(set(rth.index.date))
    completed = [d for d in days if d < today or (d == today and (now.hour > 16 or (now.hour == 16 and now.minute >= 0)))]
    if completed:
        dprev = completed[-1]
        rp = rth[rth.index.date == dprev]
        if len(rp):
            res['prev_close'] = round(float(rp['Close'].iloc[-1]), 2)
            res['prev_high'] = round(float(rp['High'].max()), 2)
            res['prev_low'] = round(float(rp['Low'].min()), 2)
            res['prev_session'] = dprev.isoformat()
            vol = rp['Volume'].fillna(0); typ = (rp['High'] + rp['Low'] + rp['Close']) / 3
            if float(vol.sum()) > 0: res['vwap'] = round(float((typ * vol).sum() / vol.sum()), 2)
    if today.weekday() < 5:
        pm = h[(idx.date == today) & ((idx.hour > 4) | ((idx.hour == 4) & (idx.minute >= 0))) & ((idx.hour < 9) | ((idx.hour == 9) & (idx.minute < 30)))]
        if len(pm):
            res['pm_high'] = round(float(pm['High'].max()), 2)
            res['pm_low'] = round(float(pm['Low'].min()), 2)
        rt = rth[rth.index.date == today]
        if len(rt):
            vol = rt['Volume'].fillna(0); typ = (rt['High'] + rt['Low'] + rt['Close']) / 3
            if float(vol.sum()) > 0: res['vwap'] = round(float((typ * vol).sum() / vol.sum()), 2)
            res['sess_high'] = round(float(rt['High'].max()), 2)
            res['sess_low'] = round(float(rt['Low'].min()), 2)
    return res

def walls(sym, idx=0, src='yahoo'):
    t = get_ticker(sym, src)
    spot, spot_ts, spot_src, hist = 0.0, None, None, None
    try:
        hist = t.history(period='5d', interval='1m', prepost=True)
        close = hist['Close'].dropna() if hist is not None and not hist.empty else None
        if close is not None and len(close):
            last = close.index[-1]
            last = last.tz_convert(ET) if getattr(last, 'tzinfo', None) else last
            spot, spot_ts, spot_src = float(close.iloc[-1]), last.isoformat(timespec='minutes'), '1m prepost bar'
    except Exception as e: errors.append(f'spot 1m {sym}: {e}')
    if not spot:
        spot = num((t.fast_info or {}).get('lastPrice')); spot_ts = datetime.datetime.now(ET).isoformat(timespec='minutes'); spot_src = 'fast_info lastPrice (fallback)'
    exps = t.options
    if not exps: raise RuntimeError('no expiries')
    now = datetime.datetime.now(ET)
    exp = exps[min(idx, len(exps) - 1)]
    ch = t.option_chain(exp)
    expdt = datetime.datetime.fromisoformat(exp).replace(hour=16, tzinfo=ET)
    T = max((expdt - now).total_seconds(), 3600) / (365 * 86400)  # floor 1h so 0DTE gamma stays finite
    rows = {}
    for side, df in (('c', ch.calls), ('p', ch.puts)):
        for _, r in df.iterrows():
            k = num(r['strike']); d = rows.setdefault(k, {'k': k, 'coi': 0, 'poi': 0, 'cv': 0, 'pv': 0, 'civ': 0, 'piv': 0})
            d[side + 'oi'] = int(num(r.get('openInterest'))); d[side + 'v'] = int(num(r.get('volume')))
            d[side + 'iv'] = num(r.get('impliedVolatility'))
            b, a = num(r.get('bid')), num(r.get('ask'))
            d[side + 'px'] = (b + a) / 2 if b > 0 and a > 0 else num(r.get('lastPrice'))
            try: d[side + 'ts'] = r.get('lastTradeDate').to_pydatetime().astimezone(ET)
            except Exception: d[side + 'ts'] = None
    strikes = sorted(rows)
    # keep strikes within ±10% of spot for wall/GEX stats
    near = [rows[k] for k in strikes if abs(k / spot - 1) <= 0.10] or [rows[k] for k in strikes]
    def iv_of(d, side):
        v = d[side + 'iv']; return v if 0.03 < v < 5 else 0.25
    def gex_at(S):  # dealer GEX convention: +call gamma, -put gamma, $ per 1% move
        g = 0.0
        for d in near:
            g += d['coi'] * bs_gamma(S, d['k'], T, iv_of(d, 'c')) * 100 * S * S * 0.01
            g -= d['poi'] * bs_gamma(S, d['k'], T, iv_of(d, 'p')) * 100 * S * S * 0.01
        return g
    gex_spot = gex_at(spot)
    # per-strike gamma exposure at spot
    for d in near:
        d['cg'] = d['coi'] * bs_gamma(spot, d['k'], T, iv_of(d, 'c')) * 100 * spot * spot * 0.01
        d['pg'] = d['poi'] * bs_gamma(spot, d['k'], T, iv_of(d, 'p')) * 100 * spot * spot * 0.01
    # gamma flip: scan spot grid ±5% for sign change of total GEX
    flip = None; grid = [spot * (0.95 + i * 0.0025) for i in range(41)]
    vals = [(S, gex_at(S)) for S in grid]
    best = None
    for (s1, g1), (s2, g2) in zip(vals, vals[1:]):
        if g1 == 0 or (g1 < 0) != (g2 < 0):
            x = s1 + (s2 - s1) * (g1 / (g1 - g2)) if g1 != g2 else s1
            if best is None or abs(x - spot) < abs(best - spot): best = x
    flip = round(best, 2) if best else None
    # max pain
    def pain(P): return sum(d['coi'] * max(P - d['k'], 0) + d['poi'] * max(d['k'] - P, 0) for d in rows.values())
    maxpain = min(strikes, key=pain)
    calls_above = [d for d in near if d['k'] >= spot] or near
    puts_below = [d for d in near if d['k'] <= spot] or near
    res = {
        'sym': sym, 'options_src': src, 'options_label': SRC_LABEL.get(src, src), 'spot': round(spot, 2), 'spot_ts': spot_ts, 'spot_src': spot_src, 'expiry': exp, 'is0dte': exp == now.date().isoformat(),
        'call_wall_oi': max(calls_above, key=lambda d: d['coi'])['k'],
        'call_wall_gamma': max(near, key=lambda d: d['cg'])['k'],
        'put_wall_oi': max(puts_below, key=lambda d: d['poi'])['k'],
        'put_wall_gamma': max(near, key=lambda d: d['pg'])['k'],
        'gamma_flip': flip, 'max_pain': maxpain,
        'net_gex_musd': round(gex_spot / 1e6, 1), 'net_gex_sign': 'positive' if gex_spot >= 0 else 'negative',
        'total_call_oi': sum(d['coi'] for d in rows.values()), 'total_put_oi': sum(d['poi'] for d in rows.values()),
        'top_calls': [{'k': d['k'], 'oi': d['coi'], 'vol': d['cv']} for d in sorted(near, key=lambda d: -d['coi'])[:5]],
        'top_puts': [{'k': d['k'], 'oi': d['poi'], 'vol': d['pv']} for d in sorted(near, key=lambda d: -d['poi'])[:5]],
    }
    atm = min((rows[k] for k in strikes if rows[k].get('cpx') and rows[k].get('ppx')), key=lambda d: abs(d['k'] - spot), default=None)
    if atm:
        sq = atm['cpx'] + atm['ppx']
        qts = min((x for x in (atm.get('cts'), atm.get('pts')) if x), default=None)
        ivm = (atm['civ'] + atm['piv']) / 2 if atm.get('civ') and atm.get('piv') else None  # raw quoted IV; scale_straddle rejects junk
        st, how = scale_straddle(sq, qts, now, expdt, spot, atm['k'], ivm)
        res.update({'atm_strike': atm['k'], 'straddle': round(st, 2), 'straddle_quote': round(sq, 2), 'straddle_method': how,
                    'straddle_quote_ts': qts.isoformat(timespec='minutes') if qts else None,
                    'range_lo': round(spot - st, 2), 'range_hi': round(spot + st, 2)})
    res['pcr_oi'] = round(res['total_put_oi'] / res['total_call_oi'], 2) if res['total_call_oi'] else None
    attach_session_levels(res, hist)
    return res

def nq_ratio():
    try:
        def _r():
            nq = yf.Ticker('NQ=F').fast_info.get('lastPrice'); q = yf.Ticker('QQQ').fast_info.get('lastPrice')
            if nq and q: return round(float(nq) / float(q), 4)
            raise RuntimeError('NQ or QQQ lastPrice missing')
        return retry(_r, tries=3, what='NQ ratio')
    except Exception as e: errors.append(f'NQ ratio: {e}')
    return None

# ---------- 2) Calendar ----------
HIGH = ['FOMC', 'Federal Funds', 'CPI', 'Non-Farm', 'Nonfarm', 'PCE', 'GDP', 'Powell', 'Fed Chair', 'Rate Decision', 'PPI', 'Unemployment Rate', 'Retail Sales']
def macro(days):
    out = []
    try:
        data = get_json('https://nfs.faireconomy.media/ff_calendar_thisweek.json', {'User-Agent': UA['User-Agent']})
    except Exception as e:
        errors.append(f'ForexFactory: {e}'); return None
    for e in data:
        if e.get('country') != 'USD': continue
        try: dt = datetime.datetime.fromisoformat(e['date']).astimezone(ET)
        except Exception: continue
        if dt.date().isoformat() not in days: continue
        imp = (e.get('impact') or '').lower()
        tag = {'high': 'high', 'medium': 'med', 'low': 'low'}.get(imp, 'low')
        if any(h.lower() in e['title'].lower() for h in HIGH) and tag == 'med': tag = 'high'
        if imp in ('holiday',): tag = 'low'
        out.append({'date': dt.date().isoformat(), 'time': dt.strftime('%H:%M') if dt.hour or dt.minute else 'All day',
                    'title': e['title'], 'impact': tag, 'forecast': e.get('forecast') or '', 'previous': e.get('previous') or ''})
    out.sort(key=lambda x: (x['date'], x['time']))
    return out

BIG = set('AAPL MSFT NVDA AMZN META GOOGL GOOG AVGO TSLA COST NFLX AMD PEP ADBE CSCO TMUS QCOM INTC TXN AMGN INTU ISRG CMCSA HON AMAT BKNG LRCX MU PANW ADP SBUX GILD MDLZ ADI REGN VRTX KLAC ASML MELI PYPL SNPS CDNS CRWD MAR ORLY CTAS ABNB PDD ARM PLTR JPM BAC WFC GS MS C V MA UNH JNJ XOM CVX WMT HD PG KO DIS BA CAT GE IBM ORCL CRM NOW UBER LLY ABT TMO MCD NKE T VZ SMCI COIN SHOP SNOW MSTR'.split())
def earnings(days):
    out = []; ok = False
    for d in days:
        try:
            j = get_json(f'https://api.nasdaq.com/api/calendar/earnings?date={d}')
            rows = (j.get('data') or {}).get('rows') or []; ok = True
        except Exception as e:
            errors.append(f'Nasdaq earnings {d}: {e}'); continue
        for r in rows:
            mc = num(str(r.get('marketCap', '0')).replace('$', '').replace(',', ''))
            sym = r.get('symbol', '')
            if mc < 20e9 and sym not in BIG: continue
            t = (r.get('time') or '').lower()
            when = 'BMO (before open)' if 'pre' in t else 'AMC (after close)' if 'after' in t else 'TBD'
            out.append({'date': d, 'sym': sym, 'name': r.get('name', ''), 'when': when, 'mcap_b': round(mc / 1e9, 1),
                        'eps_fcst': r.get('epsForecast', ''), 'qqq_top': sym in BIG,
                        'impact': 'high' if (mc >= 200e9 or sym in ('NVDA','AAPL','MSFT','AMZN','META','GOOGL','TSLA','AVGO','NFLX')) else 'med' if mc >= 50e9 else 'low'})
        time.sleep(1)
    out.sort(key=lambda x: (x['date'], -x['mcap_b']))
    return out if ok else None

# ---------- 3) Squeeze scanner ----------
BASE = 'GME AMC BBBY KOSS CVNA UPST AI SOFI PLTR MARA RIOT COIN MSTR HOOD RIVN LCID NIO TSLA SMCI CELH IONQ RGTI QUBT RKLB ASTS LUNR SOUN BBAI ACHR JOBY OPEN SPCE CHPT PLUG FCEL BYND DJT TLRY SNDL HIMS RDDT CLSK HUT WULF APLD OKLO SMR NNE SERV'.split()
def screener_syms():
    syms = []
    for q in ('most_actives', 'day_gainers', 'small_cap_gainers', 'most_shorted_stocks'):
        try:
            r = yf.screen(q, count=25)
            syms += [x['symbol'] for x in r.get('quotes', []) if x.get('symbol') and '.' not in x['symbol']]
        except Exception as e: errors.append(f'screener {q}: {e}')
        time.sleep(0.5)
    return syms
def watchlist():
    p = os.path.join(OUT, 'watchlist.txt')
    if not os.path.exists(p): return []
    return [l.strip().upper() for l in open(p) if l.strip() and not l.startswith('#')]
def scan_one(sym):
    t = yf.Ticker(sym)
    info = t.info or {}
    price = num(info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose'))
    if price <= 0: return None
    avgvol = num(info.get('averageVolume') or info.get('averageDailyVolume10Day'))
    flt = num(info.get('floatShares') or info.get('sharesOutstanding'))
    short = num(info.get('shortPercentOfFloat')) * 100
    exps = t.options
    if not exps: return None
    coi = poi = cvol = 0; ivs = []
    today = datetime.date.today()
    for e in exps[:3]:
        if (datetime.date.fromisoformat(e) - today).days > 21: break
        ch = t.option_chain(e)
        coi += int(ch.calls['openInterest'].fillna(0).sum()); poi += int(ch.puts['openInterest'].fillna(0).sum())
        cvol += int(ch.calls['volume'].fillna(0).sum())
        atm = ch.calls.iloc[(ch.calls['strike'] - price).abs().argsort()[:2]]
        ivs += [v for v in atm['impliedVolatility'].tolist() if v == v and v > 0]
        time.sleep(0.3)
    h = t.history(period='1mo', interval='1d')
    mom5 = mom20 = 0.0
    if len(h) >= 6: mom5 = (h['Close'].iloc[-1] / h['Close'].iloc[-6] - 1) * 100
    if len(h) >= 2: mom20 = (h['Close'].iloc[-1] / h['Close'].iloc[0] - 1) * 100
    iv = sum(ivs) / len(ivs) * 100 if ivs else 0
    coi_vol = coi * 100 / avgvol * 100 if avgvol else 0    # call OI shares as % of avg daily volume
    coi_flt = coi * 100 / flt * 100 if flt else 0          # call OI shares as % of float
    cv_oi = cvol / coi if coi else 0
    cp = coi / poi if poi else (coi and 5)
    score = 0; why = []
    def add(pts, cond, txt):
        nonlocal score
        if cond: score += pts; why.append(txt)
    add(min(25, short), short >= 10, f'short {short:.0f}% of float')
    add(min(20, coi_flt * 2), coi_flt >= 2, f'call OI = {coi_flt:.1f}% of float')
    add(min(15, coi_vol / 10), coi_vol >= 30, f'call OI = {coi_vol:.0f}% of avg volume')
    add(min(15, cv_oi * 15), cv_oi >= 0.5, f'call vol/OI {cv_oi:.2f} (unusual)')
    add(min(10, (cp - 1) * 5), cp >= 1.5, f'call/put OI {cp:.1f}')
    add(10, 0 < flt < 50e6, f'small float {flt/1e6:.0f}M')
    add(min(15, max(mom5, 0) / 2), mom5 >= 10, f'+{mom5:.0f}% 5-day')
    add(5, iv >= 100, f'IV {iv:.0f}%')
    return {'sym': sym, 'price': round(price, 2), 'penny': price < 5, 'call_oi': coi, 'put_oi': poi, 'cp_ratio': round(cp, 2),
            'coi_pct_avgvol': round(coi_vol, 1), 'coi_pct_float': round(coi_flt, 2), 'cvol_oi': round(cv_oi, 2),
            'short_pct': round(short, 1), 'float_m': round(flt / 1e6, 1), 'iv': round(iv, 0),
            'mom5': round(mom5, 1), 'mom20': round(mom20, 1), 'score': round(score, 1), 'why': why}

def fmt_t(t):
    return f'{t[0]}–{t[1]}' if isinstance(t, tuple) else f'{t}'

def wall_b(bias, w0, w1, spot, st, wall, rng):
    """Version B: tight (<=2 pt) band at the nearest gamma wall, plus monotonic targets."""
    R = round; put = bias == 'PUT'
    gk = 'put_wall_gamma' if put else 'call_wall_gamma'
    g = next((w.get(gk) for w in (w0, w1) if w and w.get(gk) is not None
              and ((w[gk] <= spot) if put else (w[gk] >= spot)) and abs(spot - w[gk]) <= 0.5 * st), None)
    top = R(spot)
    if put:
        bot = max(R(g), top - 2) if g is not None else top - 1
        if bot >= top: bot = top - 1
    else:
        bot = min(R(g), top + 2) if g is not None else top + 1
        if bot <= top: bot = top + 1
    side = 'under' if put else 'over'
    nm = 'put' if put else 'call'
    # Break trigger: nearest wall (gamma or OI, within 1 straddle) beyond the entry band in the bias direction.
    beyond = lambda k: (R(k) < bot) if put else (R(k) > bot)
    tc = [(R(k), lab) for k, lab in ((g, f'gamma {nm} wall'), (wall, f'OI {nm} wall'))
          if k is not None and beyond(k) and abs(k - spot) <= st]
    tc.sort(key=lambda x: -x[0] if put else x[0])
    trig, tlab = (tc[0][0], f'{tc[0][1]} {tc[0][0]}') if tc else (None, None)
    B = {'entry': f'{top}–{bot}' + (f', or a 5-minute close {side} {trig}' if trig is not None else ''),
         'setup': f"Wall entry at {f'gamma {nm} wall {R(g)}' if g is not None else 'spot'}" + (f" or break-and-hold {side} {tlab}." if trig is not None else f" only (OI {nm} wall {R(wall)} > 1 straddle away, no break trigger)."),
         'wall_entry_label': f'gamma {nm} wall {R(g)}' if g is not None else None, 'break_label': tlab, 'break_trigger': trig}
    # Candidates: gamma wall, expected-range edge (2-pt band), OI wall; keep only those beyond entry, ordered, deduped.
    m = math.floor(rng) if put else math.ceil(rng)
    cands = [R(g) if g is not None else None, (m, m + 2) if put else (m - 2, m), R(wall)]
    key = lambda t: t[0] if isinstance(t, tuple) else t
    good = [t for t in cands if t is not None and ((key(t) < top) if put else (key(t) > top))]
    if trig is not None:  # targets must lie beyond the break trigger
        past = [t for t in good if (((max(t) if isinstance(t, tuple) else t) < trig) if put else ((min(t) if isinstance(t, tuple) else t) > trig))]
        good = past
    # Spacing: a TP closer than ~0.5 straddle to the entry can't pay a cheap OTM option; drop it so the next wall beyond is used.
    near_edge = min(top, bot) if put else max(top, bot)
    dist = lambda t: (near_edge - (max(t) if isinstance(t, tuple) else t)) if put else ((min(t) if isinstance(t, tuple) else t) - near_edge)
    spaced = [t for t in good if dist(t) >= 0.45 * st]  # ~0.5 straddle, small tolerance
    if not spaced:  # nothing far enough: project 1 and 1.5 straddles beyond the entry
        spaced = [R(near_edge - st), R(near_edge - 1.5 * st)] if put else [R(near_edge + st), R(near_edge + 1.5 * st)]
    good = spaced
    good.sort(key=key, reverse=put)
    tg = []
    for t in good:
        if not tg or abs(key(t) - key(tg[-1])) >= 2: tg.append(t)
    B['tp1'] = fmt_t(tg[0]) if tg else '—'
    B['tp2'] = fmt_t(tg[1]) if len(tg) > 1 else '—'
    if len(tg) > 2: B['tp3'] = fmt_t(tg[2])
    B['stop'] = '3:30 PM ET hard stop'
    return B, tg

def zone(level):
    if level is None: return None
    f = math.floor(level)
    return f'{f}–{f + 1}'

def realized_width(w0, spot, flip):
    """A real range width from fetched fields only. Prefer the quoted/estimated straddle."""
    if w0.get('straddle'): return w0['straddle']
    cands = []
    if w0.get('range_hi') is not None and w0.get('range_lo') is not None:
        cands.append(abs(w0['range_hi'] - w0['range_lo']) / 2)
    pw, cw = w0.get('put_wall_oi'), w0.get('call_wall_oi')
    if pw is not None and cw is not None and cw > pw:
        cands.append((cw - pw) / 2)
    ph, pl = w0.get('prev_high'), w0.get('prev_low')
    if ph is not None and pl is not None and ph > pl:
        cands.append(ph - pl)
    # far flip is not used as a width — it was the unreliable signal
    return next((c for c in cands if c and c > 0), None)

def flip_usable(w0, spot, st):
    f = w0.get('gamma_flip')
    return f is not None and st and abs(f - spot) <= FLIP_MAX_STRADDLES * st

def context_bias(w0, spot, st):
    """Directional lean from prior close, VWAP/premarket, and OI-wall placement. All inputs are fetched."""
    votes, reasons = [], []
    thr = 0.25 * st if st else None
    def add(side, wgt, why):
        votes.append((side, wgt)); reasons.append(why)
    pc = w0.get('prev_close')
    if pc is not None and thr:
        d = spot - pc
        if d >= thr: add('CALL', 2, f'spot {spot} is {d:.2f} above prior close {pc}')
        elif d <= -thr: add('PUT', 2, f'spot {spot} is {-d:.2f} below prior close {pc}')
        else: add('NEUTRAL', 1, f'spot {spot} is within {abs(d):.2f} of prior close {pc}')
    pmh, pml = w0.get('pm_high'), w0.get('pm_low')
    if pc is not None and pmh is not None and pml is not None and thr:
        mid = (pmh + pml) / 2
        if mid >= pc + thr: add('CALL', 1, f'premarket mid {round(mid, 2)} is above prior close {pc}')
        elif mid <= pc - thr: add('PUT', 1, f'premarket mid {round(mid, 2)} is below prior close {pc}')
    vwap = w0.get('vwap')
    if vwap is not None and thr:
        d = spot - vwap
        if d >= thr: add('CALL', 1, f'spot is {d:.2f} above session VWAP {vwap}')
        elif d <= -thr: add('PUT', 1, f'spot is {-d:.2f} below session VWAP {vwap}')
    pw, cw = w0.get('put_wall_oi'), w0.get('call_wall_oi')
    if pw is not None and cw is not None and cw > pw:
        pos = (spot - pw) / (cw - pw)
        if pos >= 0.7: add('CALL', 1, f'spot sits in the upper part of the OI wall range {pw}–{cw}')
        elif pos <= 0.3: add('PUT', 1, f'spot sits in the lower part of the OI wall range {pw}–{cw}')
        else: add('NEUTRAL', 1, f'spot is mid-range between put wall {pw} and call wall {cw}')
    cs = sum(w for s, w in votes if s == 'CALL')
    ps = sum(w for s, w in votes if s == 'PUT')
    margin = abs(cs - ps)
    if cs - ps >= 2: bias = 'CALL'
    elif ps - cs >= 2: bias = 'PUT'
    else: bias = 'NEUTRAL'
    if bias == 'NEUTRAL':
        strength = 'weak'
    else:
        strength = 'strong' if margin >= 4 else ('moderate' if margin >= 2 else 'weak')
    why = ('; '.join(reasons) + f' (call {cs} vs put {ps}).') if reasons else 'No prior-close or wall-placement lean available; treat as a range day.'
    return bias, strength, why, reasons

def nearest_real(levels, spot, above):
    xs = [x for x in levels if x is not None and ((x > spot) if above else (x < spot))]
    return min(xs, key=lambda x: abs(x - spot)) if xs else None

def fallback_sweep(bias, w0, spot, st, flip, flip_ok):
    """A real liquidity level on the correct side of spot; never n/a."""
    R = round
    if bias == 'PUT':
        ideal = spot + 0.35 * st
        cands = [w0.get('pm_high'), w0.get('prev_high'), w0.get('sess_high'), w0.get('call_wall_oi'), w0.get('call_wall_gamma'), R(ideal)]
        cands = [x for x in cands if x is not None and x >= spot and x <= spot + st]
        if flip_ok: cands = [x for x in cands if x <= flip - 1]
        return R(min(cands, key=lambda x: abs(x - ideal))) if cands else R(spot)
    ideal = spot - 0.35 * st
    cands = [w0.get('pm_low'), w0.get('prev_low'), w0.get('sess_low'), w0.get('put_wall_oi'), w0.get('put_wall_gamma'), R(ideal)]
    cands = [x for x in cands if x is not None and x <= spot and x >= spot - st]
    if flip_ok: cands = [x for x in cands if x >= flip + 1]
    return R(max(cands, key=lambda x: -abs(x - ideal))) if cands else R(spot)

def build_range_plan(w0, w1, spot, st, lo, hi, put_wall, call_wall, strength, why, caveats):
    """NEUTRAL bias with a concrete fade-the-range A and a break B. Levels are fetched walls/range only."""
    R = round
    pw = put_wall if put_wall is not None else (R(lo) if lo < spot else R(spot - st))
    cw = call_wall if call_wall is not None else (R(hi) if hi > spot else R(spot + st))
    if pw >= spot: pw = R(spot - max(1, 0.35 * st))
    if cw <= spot: cw = R(spot + max(1, 0.35 * st))
    mid = R((pw + cw) / 2)
    fade_put = (spot - pw) <= (cw - spot)  # nearer edge is support → fade the dip (long)
    if fade_put:
        a_entry = R(pw)
        A = {'entry': f'{a_entry}',
             'setup': f'Range trade: first sweep of support {a_entry} (nearer edge of {R(pw)}–{R(cw)}). Enter on the reclaim/turn. Fade only; this is not a breakout.',
             'tp1': f'{mid}', 'tp2': f'{R(cw)}', 'stop': f'5-minute close back below {a_entry}'}
    else:
        a_entry = R(cw)
        A = {'entry': f'{a_entry}',
             'setup': f'Range trade: first sweep of resistance {a_entry} (nearer edge of {R(pw)}–{R(cw)}). Enter on the reject/turn. Fade only; this is not a breakout.',
             'tp1': f'{mid}', 'tp2': f'{R(pw)}', 'stop': f'5-minute close back above {a_entry}'}
    down1, down2 = R(pw - st), R(pw - 1.5 * st)
    up1, up2 = R(cw + st), R(cw + 1.5 * st)
    B = {'entry': f'5-minute close under {R(pw)}, or 5-minute close over {R(cw)}',
         'setup': f'Range break: follow a 5-minute hold outside the put wall/range edge {R(pw)} or the call wall/range edge {R(cw)}.',
         'tp1': f'{down1} if broken down, or {up1} if broken up',
         'tp2': f'{down2} if broken down, or {up2} if broken up',
         'stop': '3:30 PM ET hard stop',
         'wall_entry_label': None, 'break_label': f'put {R(pw)} / call {R(cw)}', 'break_trigger': None}
    inv = (f'Range {R(pw)}–{R(cw)}: if a 5-minute close outside the range is reversed back through the opposite edge '
           f'before 10:00 AM ET, the range plan is off: stand down')
    tg = f'{A["tp1"]} / {A["tp2"]} (fade) · {B["tp1"]}'
    btag = f'NEUTRAL ({strength})'
    plan = f"Today: {btag}. A: {A['entry']} fade of the nearer edge · B: {B['entry']}. Targets {tg}. Invalidation {R(pw)}–{R(cw)}."
    if caveats: plan += ' ⚠ ' + caveats[0]
    rules = RULES + ['Range day: fade first, follow only after a 5-minute hold outside the range']
    return {'plan': plan, 'spot_ts': w0.get('spot_ts'), 'bias': 'NEUTRAL', 'strength': strength, 'summary': why,
            'spot': spot, 'flip': w0.get('gamma_flip'), 'put_wall': put_wall, 'call_wall': call_wall,
            'range': [R(lo, 1), R(hi, 1)], 'straddle': st, 'straddle_method': w0.get('straddle_method', 'quote'),
            'A': A, 'B': B, 'kite': 'Rest: kite until 3:30 PM ET', 'rules': rules, 'invalidation': inv,
            'warnings': caveats or None, 'disclaimer': DISCL}

def strategy(w0, w1=None):
    """Mechanical 0DTE plan from the walls map. Always returns bias + A/B + targets + invalidation when spot exists. Not advice."""
    if not w0 or not w0.get('spot'):
        return None
    spot, flip = w0['spot'], w0.get('gamma_flip')
    st = realized_width(w0, spot, flip)
    if not st or st <= 0:
        return None
    neg = w0.get('net_gex_sign') == 'negative'
    ok = lambda k: k is not None and abs(k / spot - 1) <= 0.05
    srcs = [w for w in (w1, w0) if w]  # prefer 1DTE when 0DTE walls are degenerate
    degenerate = w0.get('put_wall_oi') == w0.get('call_wall_gamma') or not ok(w0.get('put_wall_oi')) or not ok(w0.get('call_wall_oi'))
    def pick(keys, below):
        for w in ([w0] + ([w1] if w1 else [])) if not degenerate else srcs:
            for k in keys:
                v = w.get(k)
                if ok(v) and ((v < spot) if below else (v > spot)): return v
        return None
    put_wall = pick(('put_wall_oi', 'put_wall_gamma'), True)
    call_wall = pick(('call_wall_oi', 'call_wall_gamma'), False)
    lo = w0.get('range_lo') or spot - st
    hi = w0.get('range_hi') or spot + st
    use_flip = flip_usable(w0, spot, st)
    caveats = quality_warnings(w0)
    ctx_bias, ctx_strength, ctx_why, _ = context_bias(w0, spot, st)

    if use_flip:
        d_flip = abs(spot - flip)
        strength = 'weak' if d_flip < 0.5 * st else ('moderate' if d_flip < st else 'strong')
        if spot < flip:
            bias = 'PUT'
            if not neg and strength == 'strong': strength = 'moderate'
            why = f'Spot {spot} is under the gamma flip {flip}' + (' with negative net gamma (dealers chase moves).' if neg else ' (positive gamma, moves damped).')
        elif spot > flip and not neg:
            bias = 'CALL'
            why = f'Spot {spot} is above the gamma flip {flip} with positive net gamma (dealers dampen dips).'
        else:
            # Mixed dealer signal (spot above flip, negative GEX): keep a full plan.
            if ctx_bias in ('CALL', 'PUT'):
                bias, strength, why = ctx_bias, ctx_strength, (
                    f'Spot {spot} is above the gamma flip {flip} but net gamma is negative (mixed dealer signals). '
                    f'Bias from other real levels: {ctx_why}')
                caveats = caveats + ['Mixed gamma signal: spot above flip with negative net GEX. Flip not used as the sole bias.']
            else:
                why = (f'Spot {spot} is above the gamma flip {flip} but net gamma is negative (mixed dealer signals). '
                       f'Treat as a range day. {ctx_why}')
                caveats = caveats + ['Mixed gamma signal: publishing a NEUTRAL range plan with concrete entries, not a stand-aside.']
                return build_range_plan(w0, w1, spot, st, lo, hi, put_wall, call_wall, ctx_strength or 'weak', why, caveats)
    else:
        bias, strength, why = ctx_bias, ctx_strength, ctx_why
        if flip is None:
            caveats = caveats + ['No gamma flip in the ±5% scan (GEX did not change sign). Bias from prior close / VWAP / OI walls / straddle range.']
        else:
            caveats = caveats + [f'Gamma flip {flip} is {abs(flip - spot):.1f} pts from spot {spot} (>{FLIP_MAX_STRADDLES:g}x straddle {st}); flip ignored for bias.']
        why = (('No usable gamma flip. ' if flip is None else 'Unreliable gamma flip. ') + why)
        if bias == 'NEUTRAL':
            return build_range_plan(w0, w1, spot, st, lo, hi, put_wall, call_wall, strength, why, caveats)

    R = round
    if bias == 'PUT':
        pw = put_wall or R(spot - st)
        B, tgts = wall_b('PUT', w0, w1, spot, st, pw, w0.get('range_lo') or lo)
        ideal_a = spot + 0.35 * st
        a_skip = use_flip and (ideal_a > flip - 1)
        if a_skip:
            a_entry = fallback_sweep('PUT', w0, spot, st, flip, use_flip)
            A = {'entry': f'{a_entry}',
                 'setup': f'Sweep at {a_entry} (ideal rally sat past flip−1; used the nearest real liquidity/spot-side level instead). Enter {a_entry} on the turn.',
                 'tp1': fmt_t(tgts[0]) if tgts else '—', 'tp2': fmt_t(tgts[-1]) if tgts else '—',
                 'stop': f'5-minute close back above {a_entry}'}
        else:
            cap = (flip - 1) if use_flip else (spot + st)
            a_entry = R(min(ideal_a, cap))
            if a_entry < spot:
                a_entry = fallback_sweep('PUT', w0, spot, st, flip, use_flip)
            A = {'entry': f'{a_entry}',
                 'setup': f'Open rallies to {a_entry - 1}–{a_entry}, liquidity gets swept, price snaps back down. Enter {a_entry} on the turn.',
                 'tp1': fmt_t(tgts[0]) if tgts else '—', 'tp2': fmt_t(tgts[-1]) if tgts else '—',
                 'stop': f'5-minute close back above {a_entry}'}
        inv_lvl = flip if use_flip else nearest_real([call_wall, w0.get('call_wall_oi'), w0.get('prev_high'), w0.get('pm_high'), w0.get('max_pain'), spot + st], spot, True)
        bench = f'Calls on the bench unless {zone(inv_lvl) or "resistance"} reclaims and holds'
    else:
        cw = call_wall or R(spot + st)
        B, tgts = wall_b('CALL', w0, w1, spot, st, cw, w0.get('range_hi') or hi)
        ideal_a = spot - 0.35 * st
        a_skip = use_flip and (ideal_a < flip + 1)
        if a_skip:
            a_entry = fallback_sweep('CALL', w0, spot, st, flip, use_flip)
            A = {'entry': f'{a_entry}',
                 'setup': f'Sweep at {a_entry} (ideal dip sat past flip+1; used the nearest real liquidity/spot-side level instead). Enter {a_entry} on the turn.',
                 'tp1': fmt_t(tgts[0]) if tgts else '—', 'tp2': fmt_t(tgts[-1]) if tgts else '—',
                 'stop': f'5-minute close back below {a_entry}'}
        else:
            floor = (flip + 1) if use_flip else (spot - st)
            a_entry = R(max(ideal_a, floor))
            if a_entry > spot:
                a_entry = fallback_sweep('CALL', w0, spot, st, flip, use_flip)
            A = {'entry': f'{a_entry}',
                 'setup': f'Open dips to {a_entry}–{a_entry + 1}, liquidity gets swept, price snaps back up. Enter {a_entry} on the turn.',
                 'tp1': fmt_t(tgts[0]) if tgts else '—', 'tp2': fmt_t(tgts[-1]) if tgts else '—',
                 'stop': f'5-minute close back below {a_entry}'}
        inv_lvl = flip if use_flip else nearest_real([put_wall, w0.get('put_wall_oi'), w0.get('prev_low'), w0.get('pm_low'), w0.get('max_pain'), spot - st], spot, False)
        bench = f'Puts on the bench unless price loses {zone(inv_lvl) or "support"} and holds below'
    rules = RULES + [bench]
    trig = B['entry'].split(', or ')
    b_txt = trig[0] + (f" or {trig[1]}" if len(trig) > 1 else '')
    a_txt = f"A: {A['entry']} on the turn"
    tg = ' / '.join(fmt_t(t) for t in tgts) or '—'
    fz = zone(inv_lvl) or zone(spot)
    if strength == 'weak':
        f2 = lambda k: f' {w0[k]}' if w0.get(k) is not None else ''
        liq = (f"prior-day high{f2('prev_high')} / pre-market high{f2('pm_high')}" if bias == 'CALL'
               else f"prior-day low{f2('prev_low')} / pre-market low{f2('pm_low')}")
        btag = f"{bias}, weak bias" + (f" (spot {abs(spot - flip):.1f} pts from flip, under 0.5x straddle)" if use_flip else '') + f": wait for a sweep/reject of the {liq} first"
    else:
        btag = f"{bias} ({strength})"
    plan = f"Today: {btag}. {a_txt} · B: {b_txt}. Targets {tg}. Invalidation {fz}."
    walls_lbl = ', '.join(dict.fromkeys(x for x in (B.get('wall_entry_label'), B.get('break_label')) if x))
    if walls_lbl: plan += f' ({walls_lbl}.)'
    if caveats: plan += ' ⚠ ' + caveats[0]
    inv_txt = (f'If {fz} ' + ('reclaims and holds' if bias == 'PUT' else 'is lost and holds below') +
               f' before 10:00 AM ET, the {bias.lower()} bias is off: switch sides or stand down')
    return {'plan': plan, 'spot_ts': w0.get('spot_ts'), 'bias': bias, 'strength': strength, 'summary': why, 'spot': spot,
            'flip': flip, 'put_wall': put_wall, 'call_wall': call_wall, 'range': [R(lo, 1), R(hi, 1)], 'straddle': st,
            'straddle_method': w0.get('straddle_method', 'quote'), 'A': A, 'B': B, 'kite': 'Rest: kite until 3:30 PM ET',
            'rules': rules, 'invalidation': inv_txt, 'warnings': caveats or None, 'disclaimer': DISCL}

RULES = ['No trades 9:30–10:00 AM ET: wait for confirmation (5-minute close triggers)',
         'Half-size entries; if it opens already through the wall, size half again',
         'TP1 +100%, TP2 +300%, rest kite; hard stop 3:30 PM ET']
DISCL = 'Mechanical output from delayed free data. Not financial advice.'

def main():
    now = datetime.datetime.now(ET); today = now.date()
    nxt = today + datetime.timedelta(days=1)
    while nxt.weekday() >= 5: nxt += datetime.timedelta(days=1)
    days = [today.isoformat(), nxt.isoformat()]
    brief = {'generated': now.isoformat(timespec='minutes'), 'date': today.isoformat(), 'days': days,
             'note': 'Options levels use prior-day open interest and delayed Yahoo prices. Pre-market map, not live. Not futures order-book data.'}
    brief['walls'] = []; gate = {}
    qqq_fatal = False
    for s in ('QQQ', 'SPY'):
        prev = prev_walls(s)
        w, bad = fetch_checked(s, prev)
        usable = w and not chain_fatal(w)
        if usable:
            brief.setdefault('options_source', {})[s] = w.get('options_label')
            brief['walls'].append(label_walls(w))
            wn = quality_warnings(w) + chain_soft(w, prev)
            if wn: brief.setdefault('data_warnings', {})[s] = wn
        else:
            gate[s] = bad or chain_fatal(w)
            errors.append(f'{s} unusable after retries: ' + '; '.join(gate[s]))
            if s == 'QQQ': qqq_fatal = True
        time.sleep(1)
    srcq = (brief.get('options_source') or {}).get('QQQ')
    brief['options_label'] = f'Options: {srcq}' if srcq else 'Options: no usable QQQ chain'
    brief['note'] = brief['note'].replace('delayed Yahoo prices', f'delayed prices ({srcq or "no source passed"})')
    brief['data_quality'] = {s: ('FAIL: ' + '; '.join(gate[s]) if s in gate else ('ok with warnings: ' + '; '.join(brief.get('data_warnings', {}).get(s, [])) if brief.get('data_warnings', {}).get(s) else 'ok')) for s in ('QQQ', 'SPY')}
    w0 = next((w for w in brief['walls'] if w['sym'] == 'QQQ'), None)
    if qqq_fatal or not w0 or chain_fatal(w0):
        print('Refusing to publish: QQQ spot or chain/OI still missing after retries.', file=sys.stderr)
        print('errors:', errors, file=sys.stderr)
        print('elapsed', round(time.time() - T0), 's')
        sys.exit(1)
    try:
        w1 = None
        try:
            w1 = retry(lambda: walls('QQQ', 1, w0.get('options_src', 'yahoo')), tries=3, what='QQQ 1DTE')
        except Exception as e: errors.append(f'walls QQQ 1DTE: {e}')
        if w1: brief['qqq_1dte'] = {k: w1.get(k) for k in ('expiry', 'call_wall_oi', 'call_wall_gamma', 'put_wall_oi', 'put_wall_gamma', 'gamma_flip', 'max_pain', 'net_gex_sign', 'straddle', 'range_lo', 'range_hi')}
        brief['strategy'] = strategy(w0, w1)
    except Exception as e: errors.append(f'strategy: {e}'); traceback.print_exc()
    r = nq_ratio()
    if r: brief['nq_ratio'] = r
    brief['macro'] = macro(days)
    brief['earnings'] = earnings(days)
    uni = []
    for s in watchlist() + screener_syms() + BASE:
        if s not in uni: uni.append(s)
    res = []; scanned = 0
    for s in uni:
        if time.time() - T0 > min(BUDGET, HARD - 30): errors.append(f'scanner stopped at time budget after {scanned} names'); break
        try:
            x = scan_one(s); scanned += 1
            if x: res.append(x)
        except Exception as e: print('scan', s, e)
        time.sleep(0.7)
    res.sort(key=lambda x: -x['score'])
    brief['squeeze'] = {'scanned': scanned, 'universe': len(uni), 'top': res[:10]} if res else None
    brief['errors'] = errors
    st = brief.get('strategy') or {}
    a, b_ = st.get('A') or {}, st.get('B') or {}
    plan_ok = (st.get('bias') in ('CALL', 'PUT', 'NEUTRAL') and a.get('entry') not in (None, '', 'n/a')
               and b_.get('entry') not in (None, '', 'n/a') and st.get('invalidation') and st.get('plan')
               and not st.get('data_incomplete') and 'DATA INCOMPLETE' not in str(st.get('plan') or ''))
    if not plan_ok:
        print('Refusing to publish incomplete strategy (no latest.json write).', file=sys.stderr)
        print(json.dumps({'strategy': st, 'errors': errors}, default=str)[:2000], file=sys.stderr)
        print('elapsed', round(time.time() - T0), 's')
        sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    for f in ('latest.json', f'{today.isoformat()}.json'):
        json.dump(brief, open(os.path.join(OUT, f), 'w'), separators=(',', ':'))
    # Site-wide last-updated stamp (America/Toronto / ET display)
    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    ampm = 'AM' if now.hour < 12 else 'PM'
    h12 = now.hour % 12 or 12
    stamp = {
        'iso': now.isoformat(timespec='minutes'),
        'label': f'Updated {months[now.month-1]} {now.day}, {now.year} · {h12}:{now.minute:02d} {ampm} ET',
        'source': 'morning-brief',
        'date': today.isoformat(),
    }
    json.dump(stamp, open(os.path.join(ROOT, 'data', 'updated.json'), 'w'), separators=(',', ':'))
    print(json.dumps({k: brief[k] for k in ('strategy', 'errors')}, indent=1)[:3000])
    print('elapsed', round(time.time() - T0), 's')
    print('updated', stamp['label'])
if __name__ == '__main__': main()

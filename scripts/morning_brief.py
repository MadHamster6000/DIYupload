#!/usr/bin/env python3
"""Morning Brief: QQQ/SPY 0DTE option walls, macro + earnings calendar, gamma squeeze scanner.
Free public data only (Yahoo via yfinance, ForexFactory weekly JSON, Nasdaq earnings API). No secrets.
Writes data/brief/latest.json and data/brief/YYYY-MM-DD.json. OI is prior-day; prices delayed."""
import json, os, time, math, datetime, zoneinfo, urllib.request, traceback
import yfinance as yf
ET = zoneinfo.ZoneInfo('America/New_York')
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'brief')
T0 = time.time(); BUDGET = 9 * 60
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
      'Accept': 'application/json, text/plain, */*'}
errors = []
def get_json(u, h=UA):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=30))
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

# ---------- Data-quality gate ----------
# A partial Yahoo chain looks like a real one but shifts every level. Trip when any of:
OI_DROP_MAX = 0.50        # total OI down more than 50% vs the previous run
PCR_MAX = 3.0             # put/call OI ratio above 3
FLIP_WARN_STRADDLES = 1.0  # > 1 straddle: warning only, plan still emitted
FLIP_MAX_STRADDLES = 2.0  # > 2 straddles: hard fail / retry
def quality_check(w, prev=None):
    bad = []
    if not w: return ['no walls']
    tot = (w.get('total_call_oi') or 0) + (w.get('total_put_oi') or 0)
    # Only compare like with like: OI differs hugely between expiries (e.g. Fri monthly vs Mon weekly),
    # so the drop rule applies when the previous run was for the same expiry (a same-day rerun).
    same = prev and prev.get('expiry') == w.get('expiry')
    ptot = ((prev.get('total_call_oi') or 0) + (prev.get('total_put_oi') or 0)) if same else 0
    if ptot and tot < (1 - OI_DROP_MAX) * ptot: bad.append(f'total OI {tot:,} is down {100 * (1 - tot / ptot):.0f}% vs last run ({ptot:,})')
    if (w.get('pcr_oi') or 0) > PCR_MAX: bad.append(f"put/call OI ratio {w['pcr_oi']} > {PCR_MAX}")
    st, f = w.get('straddle'), w.get('gamma_flip')
    if st and f is not None and abs(f - w['spot']) > FLIP_MAX_STRADDLES * st:
        bad.append(f"gamma flip {f} is {abs(f - w['spot']):.1f} pts from spot {w['spot']} (> {FLIP_MAX_STRADDLES:g} x straddle {st})")
    return bad
def quality_warnings(w):
    """Soft checks: shown in the brief, plan still emitted."""
    st, f = (w or {}).get('straddle'), (w or {}).get('gamma_flip')
    if st and f is not None and FLIP_WARN_STRADDLES * st < abs(f - w['spot']) <= FLIP_MAX_STRADDLES * st:
        return [f"WARNING: gamma flip {f} is {abs(f - w['spot']) / st:.1f}x straddle from spot {w['spot']} (straddle {st}); flip-based bias less reliable"]
    return []
def prev_walls(sym):
    try:
        b = json.load(open(os.path.join(OUT, 'latest.json')))
        return next((w for w in b.get('walls', []) if w.get('sym') == sym), None)
    except Exception: return None
def fetch_checked(sym, prev, tries=3, backoff=(10, 30)):
    """walls() with the quality gate; retry with backoff. Returns (walls, reasons-or-[])."""
    w, bad = None, ['not fetched']
    for i in range(tries):
        try:
            w = walls(sym); bad = quality_check(w, prev)
        except Exception as e: bad = [f'walls {sym}: {e}']
        if not bad: return w, []
        print(f'quality gate {sym} try {i + 1}/{tries}:', bad)
        if i < tries - 1: time.sleep(backoff[min(i, len(backoff) - 1)])
    return w, bad

def label_walls(w):
    if not w: return w
    w['labels'] = {'gamma_call_wall': f"gamma call wall {w.get('call_wall_gamma')}", 'oi_call_wall': f"OI call wall {w.get('call_wall_oi')}",
                   'gamma_put_wall': f"gamma put wall {w.get('put_wall_gamma')}", 'oi_put_wall': f"OI put wall {w.get('put_wall_oi')}",
                   'use': 'gamma walls = wall entry; OI walls = break trigger'}
    return w

# ---------- 1) Walls ----------
def walls(sym, idx=0):
    t = yf.Ticker(sym)
    spot, spot_ts, spot_src = 0.0, None, None
    try:
        h = t.history(period='2d', interval='1m', prepost=True)['Close'].dropna()
        if len(h): spot, spot_ts, spot_src = float(h.iloc[-1]), h.index[-1].tz_convert(ET).isoformat(timespec='minutes'), '1m prepost bar'
    except Exception as e: errors.append(f'spot 1m {sym}: {e}')
    if not spot:
        spot = num(t.fast_info.get('lastPrice')); spot_ts = datetime.datetime.now(ET).isoformat(timespec='minutes'); spot_src = 'fast_info lastPrice (fallback)'
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
        'sym': sym, 'spot': round(spot, 2), 'spot_ts': spot_ts, 'spot_src': spot_src, 'expiry': exp, 'is0dte': exp == now.date().isoformat(),
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
    return res

def nq_ratio():
    try:
        nq = yf.Ticker('NQ=F').fast_info.get('lastPrice'); q = yf.Ticker('QQQ').fast_info.get('lastPrice')
        if nq and q: return round(float(nq) / float(q), 4)
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
    # Break trigger: OI wall only if within 1 straddle of spot; else gamma-wall break if it is beyond the entry band; else none.
    trig, tlab = None, None
    if wall is not None and abs(wall - spot) <= st:
        trig, tlab = R(wall), f'OI {nm} wall {R(wall)}'
    elif g is not None and ((R(g) < bot) if put else (R(g) > bot)):
        trig, tlab = R(g), f'gamma {nm} wall {R(g)} break'
    B = {'entry': f'{top}–{bot}' + (f', or a 5-minute close {side} {trig}' if trig is not None else ''),
         'setup': f"Wall entry at {f'gamma {nm} wall {R(g)}' if g is not None else 'spot'}" + (f" or break-and-hold {side} {tlab}." if trig is not None else f" only (OI {nm} wall {R(wall)} > 1 straddle away, no break trigger)."),
         'wall_entry_label': f'gamma {nm} wall {R(g)}' if g is not None else None, 'break_label': tlab, 'break_trigger': trig}
    # Candidates: gamma wall, expected-range edge (2-pt band), OI wall; keep only those beyond entry, ordered, deduped.
    m = math.floor(rng) if put else math.ceil(rng)
    cands = [R(g) if g is not None else None, (m, m + 2) if put else (m - 2, m), R(wall)]
    key = lambda t: t[0] if isinstance(t, tuple) else t
    good = [t for t in cands if t is not None and ((key(t) < top) if put else (key(t) > top))]
    if trig is not None:  # targets are exits: drop any at or beyond the break trigger
        far = lambda t: (min(t) if isinstance(t, tuple) else t) <= trig if put else (max(t) if isinstance(t, tuple) else t) >= trig
        kept = [t for t in good if not far(t)]
        if kept: good = kept
        else:  # trigger sits on/inside every target: too close to the entry to be useful, drop it
            trig = None; B['entry'] = f'{top}–{bot}'; B['break_label'] = None; B['break_trigger'] = None
            B['setup'] = f"Wall entry at {f'gamma {nm} wall {R(g)}' if g is not None else 'spot'} only (break level overlaps targets)."
    good.sort(key=key, reverse=put)
    tg = []
    for t in good:
        if not tg or abs(key(t) - key(tg[-1])) >= 2: tg.append(t)
    B['tp1'] = fmt_t(tg[0]) if tg else '—'
    B['tp2'] = fmt_t(tg[1]) if len(tg) > 1 else '—'
    if len(tg) > 2: B['tp3'] = fmt_t(tg[2])
    B['stop'] = '3:30 PM ET hard stop'
    return B, tg

def strategy(w0, w1=None):
    """Mechanical 0DTE plan from the walls map. Not advice."""
    spot, flip = w0['spot'], w0.get('gamma_flip')
    if not flip: return None
    neg = w0['net_gex_sign'] == 'negative'
    ok = lambda k: k is not None and abs(k / spot - 1) <= 0.05
    srcs = [w for w in (w1, w0) if w]  # prefer 1DTE when 0DTE walls are degenerate
    def pick(keys, below):
        for w in ([w0] + ([w1] if w1 else [])) if not degenerate else srcs:
            for k in keys:
                v = w.get(k)
                if ok(v) and ((v < spot) if below else (v > spot)): return v
        return None
    degenerate = w0.get('put_wall_oi') == w0.get('call_wall_gamma') or not ok(w0.get('put_wall_oi')) or not ok(w0.get('call_wall_oi'))
    # Break trigger = OI walls (both sides); wall entry = gamma walls (see wall_b).
    put_wall = pick(('put_wall_oi', 'put_wall_gamma'), True)
    call_wall = pick(('call_wall_oi', 'call_wall_gamma'), False)
    st = w0.get('straddle') or abs(flip - spot)
    lo = (w1 or {}).get('range_lo') or w0.get('range_lo') or spot - 2 * st
    hi = (w1 or {}).get('range_hi') or w0.get('range_hi') or spot + 2 * st
    fz = f'{math.floor(flip)}–{math.floor(flip) + 1}'
    d_flip = abs(spot - flip)
    strength = 'weak' if d_flip < 0.5 * st else ('moderate' if d_flip < st else 'strong')
    if spot < flip:
        bias = 'PUT'
        if not neg and strength == 'strong': strength = 'moderate'  # positive gamma damps moves
    elif spot > flip and not neg:
        bias = 'CALL'
    else:
        return {'plan': f'Today: NEUTRAL, stand aside; watch the flip {fz}.', 'bias': 'NEUTRAL', 'summary': f'Spot {spot} above flip {flip} but net gamma negative: mixed signals, stand aside or wait for a clean 5-min trend.',
                'invalidation': fz, 'rules': RULES, 'disclaimer': DISCL}
    R = round
    a_skip = False
    if bias == 'PUT':
        pw = put_wall or R(spot - st)
        # Sweep = rally into liquidity above spot, capped under the flip.
        # Skip when the flip-1 cap would crush the ideal rally (spot too close to flip).
        ideal_a = spot + 0.35 * st
        flip_cap = flip - 1
        B, tgts = wall_b('PUT', w0, w1, spot, st, pw, w0.get('range_lo') or lo)
        if ideal_a > flip_cap:
            a_skip = True
            A = {'entry': 'n/a', 'setup': 'Sweep entry skipped: spot too close to the gamma flip (ideal rally sits above flip−1). Use Version B (wall entry) only.',
                 'tp1': '—', 'tp2': '—', 'stop': '—'}
        else:
            a_entry = R(min(ideal_a, flip_cap))
            # Rally must be at/above spot (mirror of call dip ≤ spot).
            if a_entry < spot:
                a_skip = True
                A = {'entry': 'n/a', 'setup': 'Sweep entry skipped: clamped level is below spot (not a valid rally). Use Version B (wall entry) only.',
                     'tp1': '—', 'tp2': '—', 'stop': '—'}
            else:
                A = {'entry': f'{a_entry}', 'setup': f'Open rallies to {a_entry - 1}–{a_entry}, liquidity gets swept, price snaps back down. Enter {a_entry} on the turn.',
                     'tp1': fmt_t(tgts[0]) if tgts else '—', 'tp2': fmt_t(tgts[-1]) if tgts else '—', 'stop': f'5-minute close back above {a_entry}'}
        bench = f'Calls on the bench unless {fz} reclaims and holds'
        why = f'Spot {spot} is under the gamma flip {flip}' + (' with negative net gamma (dealers chase moves).' if neg else ' (positive gamma, moves damped).')
    else:
        cw = call_wall or R(spot + st)
        # Sweep = dip into liquidity below spot, floored above the flip.
        # Skip when the flip+1 floor would lift the ideal dip (spot too close to flip).
        ideal_a = spot - 0.35 * st
        flip_floor = flip + 1
        B, tgts = wall_b('CALL', w0, w1, spot, st, cw, w0.get('range_hi') or hi)
        if ideal_a < flip_floor:
            a_skip = True
            A = {'entry': 'n/a', 'setup': 'Sweep entry skipped: spot too close to the gamma flip (ideal dip sits below flip+1). Use Version B (wall entry) only.',
                 'tp1': '—', 'tp2': '—', 'stop': '—'}
        else:
            a_entry = R(max(ideal_a, flip_floor))
            # Dip must be at/below spot.
            if a_entry > spot:
                a_skip = True
                A = {'entry': 'n/a', 'setup': 'Sweep entry skipped: clamped level is above spot (not a valid dip). Use Version B (wall entry) only.',
                     'tp1': '—', 'tp2': '—', 'stop': '—'}
            else:
                A = {'entry': f'{a_entry}', 'setup': f'Open dips to {a_entry}–{a_entry + 1}, liquidity gets swept, price snaps back up. Enter {a_entry} on the turn.',
                     'tp1': fmt_t(tgts[0]) if tgts else '—', 'tp2': fmt_t(tgts[-1]) if tgts else '—', 'stop': f'5-minute close back below {a_entry}'}
        bench = f'Puts on the bench unless price loses {fz} and holds below'
        why = f'Spot {spot} is above the gamma flip {flip} with positive net gamma (dealers dampen dips).'
    rules = RULES + [bench]
    trig = B['entry'].split(', or ')
    b_txt = trig[0] + (f" or {trig[1]}" if len(trig) > 1 else '')
    a_txt = 'A skipped (spot too close to flip)' if a_skip else f"A: {A['entry']} on the turn"
    tg = ' / '.join(fmt_t(t) for t in tgts) or '—'
    if strength == 'weak':
        f2 = lambda k: f' {w0[k]}' if w0.get(k) is not None else ''
        liq = (f"prior-day high{f2('prev_high')} / pre-market high{f2('pm_high')}" if bias == 'CALL'
               else f"prior-day low{f2('prev_low')} / pre-market low{f2('pm_low')}")
        btag = f"{bias}, weak bias (spot {abs(spot - flip):.1f} pts from flip, under 0.5x straddle): wait for a sweep/reject of the {liq} first"
    else:
        btag = f"{bias} ({strength})"
    plan = f"Today: {btag}. {a_txt} · B: {b_txt}. Targets {tg}. Invalidation {fz}."
    walls_lbl = ', '.join(x for x in (B.get('wall_entry_label'), B.get('break_label')) if x)
    if walls_lbl: plan += f' ({walls_lbl}.)'
    return {'plan': plan, 'spot_ts': w0.get('spot_ts'), 'bias': bias, 'strength': strength, 'summary': why, 'spot': spot, 'flip': flip, 'put_wall': put_wall, 'call_wall': call_wall,
            'range': [R(lo, 1), R(hi, 1)], 'straddle': st, 'straddle_method': w0.get('straddle_method', 'quote'), 'A': A, 'B': B, 'kite': 'Rest: kite until 3:30 PM ET', 'rules': rules,
            'invalidation': f'If {fz} ' + ('reclaims and holds' if bias == 'PUT' else 'is lost and holds below') + f' before 10:00 AM ET, the {bias.lower()} bias is off: switch sides or stand down',
            'disclaimer': DISCL}

RULES = ['No trades 9:30–10:00 AM ET: wait for confirmation (5-minute close triggers)',
         'Half-size entries; if it opens already through the wall, size half again',
         'TP1 +100%, TP2 +300%, rest kite; hard stop 3:30 PM ET']
DISCL = 'Mechanical output from delayed free data. Not financial advice.'

def incomplete_plan(reasons):
    return {'plan': 'DATA INCOMPLETE — levels unreliable. Today: NEUTRAL, no mechanical plan.', 'bias': 'NEUTRAL', 'strength': 'n/a',
            'summary': 'Options chain failed the data-quality gate after retries: ' + '; '.join(reasons), 'data_incomplete': True,
            'rules': RULES, 'disclaimer': DISCL}

def main():
    now = datetime.datetime.now(ET); today = now.date()
    nxt = today + datetime.timedelta(days=1)
    while nxt.weekday() >= 5: nxt += datetime.timedelta(days=1)
    days = [today.isoformat(), nxt.isoformat()]
    brief = {'generated': now.isoformat(timespec='minutes'), 'date': today.isoformat(), 'days': days,
             'note': 'Options levels use prior-day open interest and delayed Yahoo prices. Pre-market map, not live. Not futures order-book data.'}
    brief['walls'] = []; gate = {}
    for s in ('QQQ', 'SPY'):
        w, bad = fetch_checked(s, prev_walls(s))
        if w: brief['walls'].append(label_walls(w))
        if w and not bad:
            wn = quality_warnings(w)
            if wn: brief.setdefault('data_warnings', {})[s] = wn
        if bad: gate[s] = bad; errors.append(f'DATA INCOMPLETE {s}: ' + '; '.join(bad))
        time.sleep(1)
    brief['data_quality'] = {s: ('FAIL: ' + '; '.join(gate[s]) if s in gate else 'ok') for s in ('QQQ', 'SPY')}
    try:
        w0 = next((w for w in brief['walls'] if w['sym'] == 'QQQ'), None); w1 = None
        try: w1 = walls('QQQ', 1)
        except Exception as e: errors.append(f'walls QQQ 1DTE: {e}')
        if w1: brief['qqq_1dte'] = {k: w1.get(k) for k in ('expiry', 'call_wall_oi', 'call_wall_gamma', 'put_wall_oi', 'put_wall_gamma', 'gamma_flip', 'max_pain', 'net_gex_sign', 'straddle', 'range_lo', 'range_hi')}
        brief['strategy'] = incomplete_plan(gate['QQQ']) if 'QQQ' in gate else (strategy(w0, w1) if w0 else None)
        wq = brief.get('data_warnings', {}).get('QQQ')
        if wq and brief['strategy'] and 'plan' in brief['strategy']:
            brief['strategy']['warnings'] = wq; brief['strategy']['plan'] += ' ⚠ ' + wq[0]
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
        if time.time() - T0 > BUDGET: errors.append(f'scanner stopped at time budget after {scanned} names'); break
        try:
            x = scan_one(s); scanned += 1
            if x: res.append(x)
        except Exception as e: print('scan', s, e)
        time.sleep(0.7)
    res.sort(key=lambda x: -x['score'])
    brief['squeeze'] = {'scanned': scanned, 'universe': len(uni), 'top': res[:10]} if res else None
    brief['errors'] = errors
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

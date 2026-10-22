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

# ---------- 1) Walls ----------
def walls(sym, idx=0):
    t = yf.Ticker(sym)
    spot = num(t.fast_info.get('lastPrice'))
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
        'sym': sym, 'spot': round(spot, 2), 'expiry': exp, 'is0dte': exp == now.date().isoformat(),
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
        st = atm['cpx'] + atm['ppx']
        res.update({'atm_strike': atm['k'], 'straddle': round(st, 2), 'range_lo': round(spot - st, 2), 'range_hi': round(spot + st, 2)})
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
    put_wall = pick(('put_wall_oi', 'put_wall_gamma'), True)
    call_wall = pick(('call_wall_gamma', 'call_wall_oi', 'max_pain'), False)
    st = w0.get('straddle') or abs(flip - spot)
    lo = (w1 or {}).get('range_lo') or w0.get('range_lo') or spot - 2 * st
    hi = (w1 or {}).get('range_hi') or w0.get('range_hi') or spot + 2 * st
    fz = f'{math.floor(flip)}–{math.floor(flip) + 1}'
    if spot < flip:
        bias = 'PUT'; strength = 'strong' if neg else 'weak (positive gamma, expect chop)'
    elif spot > flip and not neg:
        bias = 'CALL'; strength = 'strong'
    else:
        return {'plan': f'Today: NEUTRAL, stand aside; watch the flip {fz}.', 'bias': 'NEUTRAL', 'summary': f'Spot {spot} above flip {flip} but net gamma negative: mixed signals, stand aside or wait for a clean 5-min trend.',
                'invalidation': fz, 'rules': RULES, 'disclaimer': DISCL}
    R = round
    if bias == 'PUT':
        pw = put_wall or R(spot - st)
        a_entry = R(min(spot + 0.35 * st, flip - 1))
        A = {'entry': f'{a_entry}', 'setup': f'Open rallies to {a_entry - 1}–{a_entry}, liquidity gets swept, price snaps back down. Enter {a_entry} on the turn.',
             'tp1': f'{R(spot)}–{R(spot) - 1}', 'tp2': f'{R(pw)}', 'stop': f'5-minute close back above {a_entry}'}
        t2 = math.floor(lo)
        B = {'entry': f'{R(pw) + 2}–{R(spot)}, or a 5-minute close under {R(pw)}', 'setup': 'Wall entry near spot or break-and-hold under the put wall.',
             'tp1': f'{R(pw)}', 'tp2': f'{t2}–{t2 + 2}', 'stop': '3:30 PM ET hard stop'}
        bench = f'Calls on the bench unless {fz} reclaims and holds'
        why = f'Spot {spot} is under the gamma flip {flip}' + (' with negative net gamma (dealers chase moves).' if neg else ' (positive gamma, moves damped).')
    else:
        cw = call_wall or R(spot + st)
        a_entry = R(max(spot - 0.35 * st, flip + 1))
        A = {'entry': f'{a_entry}', 'setup': f'Open dips to {a_entry}–{a_entry + 1}, liquidity gets swept, price snaps back up. Enter {a_entry} on the turn.',
             'tp1': f'{R(spot)}–{R(spot) + 1}', 'tp2': f'{R(cw)}', 'stop': f'5-minute close back below {a_entry}'}
        t2 = math.ceil(hi)
        B = {'entry': f'{R(spot)}–{R(cw) - 2}, or a 5-minute close over {R(cw)}', 'setup': 'Wall entry near spot or break-and-hold over the call wall.',
             'tp1': f'{R(cw)}', 'tp2': f'{t2 - 2}–{t2}', 'stop': '3:30 PM ET hard stop'}
        bench = f'Puts on the bench unless price loses {fz} and holds below'
        why = f'Spot {spot} is above the gamma flip {flip} with positive net gamma (dealers dampen dips).'
    rules = RULES + [bench]
    plan = f"Today: {bias}, entry {B['entry'].split(',')[0]}, targets {B['tp1']} / {B['tp2']}, invalidation {fz}."
    return {'plan': plan, 'bias': bias, 'strength': strength, 'summary': why, 'spot': spot, 'flip': flip, 'put_wall': put_wall, 'call_wall': call_wall,
            'range': [R(lo, 1), R(hi, 1)], 'A': A, 'B': B, 'kite': 'Rest: kite until 3:30 PM ET', 'rules': rules,
            'invalidation': f'If {fz} ' + ('reclaims and holds' if bias == 'PUT' else 'is lost and holds below') + f' before 10:00 AM ET, the {bias.lower()} bias is off: switch sides or stand down',
            'disclaimer': DISCL}

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
    brief['walls'] = []
    for s in ('QQQ', 'SPY'):
        try: brief['walls'].append(walls(s))
        except Exception as e: errors.append(f'walls {s}: {e}'); traceback.print_exc()
        time.sleep(1)
    try:
        w0 = next((w for w in brief['walls'] if w['sym'] == 'QQQ'), None); w1 = None
        try: w1 = walls('QQQ', 1)
        except Exception as e: errors.append(f'walls QQQ 1DTE: {e}')
        if w1: brief['qqq_1dte'] = {k: w1.get(k) for k in ('expiry', 'call_wall_oi', 'call_wall_gamma', 'put_wall_oi', 'put_wall_gamma', 'gamma_flip', 'max_pain', 'net_gex_sign', 'straddle', 'range_lo', 'range_hi')}
        brief['strategy'] = strategy(w0, w1) if w0 else None
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
    print(json.dumps({k: brief[k] for k in ('strategy', 'errors')}, indent=1)[:3000])
    print('elapsed', round(time.time() - T0), 's')
main()

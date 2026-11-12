"""Daily data update for the Freedom UA site.

Pulls Higher League (FBU) results, box scores, schedule and standings,
plus EYBL junior games (eybl.tv + FIBA LiveStats), and rewrites
games.js / eybl.js. Keeps a state file so games are never lost.
Run: python scripts/update.py
"""
import asyncio, json, os, re, sys, urllib.request, datetime as dt
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'data', 'state.json')
LEAGUE, SEASON = 8185, 133439
FBU = 'https://fbu.ua/statistics/league-%d' % LEAGUE
EYBL_TEAM = 'https://eybl.tv/boys/team/204838/freedom-ua-basketball-academy'
EYBL20_TEAM = 'https://eybl.tv/boys/team/202188/freedom-ua-basketball-academy'
EYBL_TEAMS = [('eybl', EYBL_TEAM), ('eybl20', EYBL20_TEAM)]
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'

# Ukrainian surname fragment -> site player id (senior squad)
FBU_PLAYERS = {'Ліщин': 'lishchyna', 'ЛIщин': 'lishchyna', 'Горб': 'horb', 'Свиридов': 'svyrydov',
    'Максим Мануйлик': 'm-manuilyk', 'Роман Мануйлик': 'r-manuilyk', 'Михайлович': 'mykhailovych',
    'Ганицьк': 'hanytskyi', 'Вакуленк': 'vakulenko', 'Супрун': 'suprun', 'Бабич': 'babych', 'Бабіч': 'babych',
    'Бондар': 'bondar', 'Топольник': 'topolnyk', 'Рудоманенк': 'rudomanenko', 'Рубленк': 'rublenko',
    'Бахтєєв': 'bakhtieiev', 'Бахтеєв': 'bakhtieiev'}
# FIBA LiveStats family name fragment -> site id (EYBL juniors)
EYBL_PLAYERS = {'Koretsk': 'j-koretskyi', 'Bilenko': 'j-bilenko', 'Manylyk': 'm-manuilyk', 'Manuilyk': 'm-manuilyk',
    'Struikov': 'j-striukov', 'Striukov': 'j-striukov', 'Samokhat': 'j-samokhatny', 'Suprun': 'suprun',
    'Solomyanikov': 'j-solomyanikov', 'Bezsyd': 'j-bezsudnyi', 'Bezsud': 'j-bezsudnyi', 'Shvetsov': 'j-shvetsov',
    'Khodzin': 'j-khodzinskyi', 'Sabirov': 'j-sabirov', 'Arkhypenko': 'j-arkhypenko', 'Didusenko': 'j-didusenko',
    'Volzhyn': 'j-volzhyn', 'Derkach': 'j-derkach', 'Genchmazlumo': 'j-genchmazlumo', 'Skliar': 'j-skliar', 'Sklyar': 'j-skliar',
    # senior squad (EYBL U20)
    'Lishch': 'lishchyna', 'Lyshch': 'lishchyna', 'Horb': 'horb', 'Svyryd': 'svyrydov', 'Sviryd': 'svyrydov',
    'Mykhailov': 'mykhailovych', 'Mykhaylov': 'mykhailovych', 'Hanytsk': 'hanytskyi', 'Ganytsk': 'hanytskyi',
    'Vakulenk': 'vakulenko', 'Babych': 'babych', 'Babich': 'babych', 'Bondar': 'bondar', 'Topoln': 'topolnyk',
    'Rudomanenk': 'rudomanenko', 'Rublenk': 'rublenko', 'Bakhtie': 'bakhtieiev', 'Bakhte': 'bakhtieiev'}
TEAMS = {'ЧОДЮСШ': ('CHEBASKET', 'CHEBASKET (Chernivtsi)'), 'ПОЛІССЯ': ('Polissya', 'Polissya-Zhytomyr Polytechnic'),
    'ДІДІБАО': ('DiDiBao', 'DiDiBao (Kamianets-Podilskyi)'), 'ЧАЙКА': ('Chaika-VMSU', 'Chaika-VMSU (Odesa)'),
    'НІКО': ('Niko-Basket-2', 'Niko-Basket-2 (Mykolaiv)')}


def team_names(raw):
    up = raw.upper()
    for k, v in TEAMS.items():
        if k in up:
            return v
    return raw, raw


def pid_fbu(name):
    for k, v in FBU_PLAYERS.items():
        if k in name:
            return v


def pid_eybl(fam, first=''):
    if 'manuil' in fam.lower() or 'manyl' in fam.lower():
        return 'r-manuilyk' if first.lower().startswith('rom') else 'm-manuilyk'
    for k, v in EYBL_PLAYERS.items():
        if k.lower() in fam.lower():
            return v


def opp_from_url(u):
    parts = [x for x in u.split('/match/')[-1].split('/')[1:] if x and 'freedom' not in x]
    if not parts:
        return ''
    small = {'bc', 'bk', 'kk', 'ba', 'bcm', 'skup', 'ksk', 'sk', 'mbk', 'bkm'}
    return ' '.join(w.upper() if w in small else w.capitalize() for w in parts[0].split('-'))


def num(x):
    try:
        return int(x)
    except Exception:
        return 0


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {'fbu': {}, 'eybl': {}, 'standings': []}


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


async def fbu_calendar(pg):
    await pg.goto(f'{FBU}/calendar?season_id={SEASON}', timeout=60000)
    await pg.wait_for_selector('.main_container table', timeout=45000)
    await pg.wait_for_timeout(1500)
    rows = await pg.eval_on_selector_all('.main_container table tr', '''rs=>rs.map(r=>({c:[...r.querySelectorAll("td")].map(t=>t.innerText.trim()),
        g:[...r.querySelectorAll("a")].map(a=>a.getAttribute("href")||"").filter(h=>/game-\\d+/.test(h))}))''')
    out = {}
    for r in rows:
        if not any('FREEDOM' in c.upper() for c in r['c']) or not r['g']:
            continue
        gid = re.search(r'game-(\d+)', r['g'][0]).group(1)
        d = re.match(r'(\d\d)/(\d\d)/(\d{4})', r['c'][0] or '')
        home = 'FREEDOM' in (r['c'][4] if len(r['c']) > 6 else '').upper()
        opp_raw = (r['c'][6] if home else r['c'][4]) if len(r['c']) > 6 else ''
        out[gid] = {'date': f'{d.group(3)}-{d.group(2)}-{d.group(1)}' if d else None, 'home': home,
                    'opp': team_names(opp_raw)[0] if opp_raw else None, 'oppFull': team_names(opp_raw)[1] if opp_raw else None}
    return out


async def fbu_standings(pg):
    await pg.goto(f'{FBU}/standings?season_id={SEASON}', timeout=60000)
    await pg.wait_for_selector('.main_container table', timeout=45000)
    await pg.wait_for_timeout(1500)
    rows = await pg.eval_on_selector_all('.main_container table tr', 'rs=>rs.map(r=>[...r.querySelectorAll("td")].map(t=>t.innerText.trim()))')
    st = []
    for c in rows:
        if len(c) >= 5 and re.match(r'^\d+\.?$', c[0]) and c[2].isdigit():
            st.append([team_names(c[1])[0] if 'FREEDOM' not in c[1].upper() else 'Freedom UA', int(c[2]), int(c[3]), int(c[4])])
    return st


async def fbu_game(pg, gid):
    await pg.goto(f'{FBU}/game-{gid}?season_id={SEASON}', timeout=60000)
    await pg.wait_for_selector('#game', timeout=45000)
    await pg.wait_for_timeout(4000)
    head = await pg.inner_text('#game')
    m = re.search(r'ГРА:\s*(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)', head.split('\n')[0])
    when = re.search(r'(\d\d)/(\d\d)/(\d{4})\s+(\d\d:\d\d)', head)
    arena = re.search(r'арена:\s*(.+)', head)
    info = {'date': f'{when.group(3)}-{when.group(2)}-{when.group(1)}' if when else None,
            'time': when.group(4) if when else None, 'venue': arena.group(1).strip() if arena else ''}
    if not m:
        return info
    home_raw, hs, as_, away_raw = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    home = 'FREEDOM' in home_raw.upper()
    opp_raw = away_raw if home else home_raw
    info.update(home=home, opp=team_names(opp_raw)[0], oppFull=team_names(opp_raw)[1],
                us=hs if home else as_, them=as_ if home else hs)
    if hs + as_ == 0:
        return info
    try:
        await pg.get_by_text('протокол', exact=True).first.click()
        await pg.wait_for_timeout(3500)
    except Exception:
        return info
    tables = await pg.eval_on_selector_all('#game table', 'ts=>ts.map(t=>[...t.querySelectorAll("tr")].map(r=>[...r.querySelectorAll("td,th")].map(c=>c.innerText.trim())))')
    best = {}
    for t in tables:
        lines = {}
        for c in t:
            if len(c) < 19 or not c[0].isdigit():
                continue
            name = c[1].split('\n')[0].strip()
            start = name.startswith('*')
            p = pid_fbu(name.lstrip('*'))
            if not p:
                continue
            d = c[2:]
            lines[p] = dict(n=int(c[0]), name=name.lstrip('*'), start=start, min=d[0], oreb=num(d[7]), dreb=num(d[8]),
                            reb=num(d[9]), ast=num(d[10]), pf=num(d[11]), tov=num(d[12]), stl=num(d[13]), blk=num(d[14]),
                            eff=num(d[15]), pm=num(d[16]), pts=num(d[17]))
        if len(lines) > len(best):
            best = lines
    if best:
        info['lines'] = best
        top = max(best.items(), key=lambda kv: kv[1]['pts'])
        info['top'] = [top[0], top[1]['pts']]
        info['win'] = info['us'] > info['them']
    return info


async def eybl_matches(pg, team_url=EYBL_TEAM):
    await pg.goto(team_url, timeout=60000)
    await pg.wait_for_timeout(6000)
    links = await pg.eval_on_selector_all('a[href*="/match/"]', 'as=>as.map(a=>a.href)')
    return sorted(set(re.search(r'/match/(\d+)', h).group(1) for h in links if re.search(r'/match/(\d+)', h))), \
        {re.search(r'/match/(\d+)', h).group(1): h for h in links if re.search(r'/match/(\d+)', h)}


def eybl_game(gid, url):
    d = fetch_json(f'https://fibalivestats.dcd.shared.geniussports.com/data/{gid}/data.json')
    k = '1' if 'freedom' in d['tm']['1']['name'].lower() else '2'
    o = '2' if k == '1' else '1'
    us, them = d['tm'][k].get('score', 0), d['tm'][o].get('score', 0)
    lines = {}
    for p in d['tm'][k].get('pl', {}).values():
        pid = pid_eybl(p.get('familyName', ''), p.get('firstName', ''))
        if not pid or not p.get('sMinutes') or p['sMinutes'] in ('0:00', '00:00'):
            continue
        lines[pid] = dict(n=num(p.get('shirtNumber')), min=p['sMinutes'], pts=p.get('sPoints', 0), reb=p.get('sReboundsTotal', 0),
                          ast=p.get('sAssists', 0), stl=p.get('sSteals', 0), blk=p.get('sBlocks', 0), tov=p.get('sTurnovers', 0),
                          eff=p.get('eff_1') or 0, start=bool(p.get('starter')))
    g = dict(id=gid, opp=d['tm'][o]['name'], oppFull=d['tm'][o]['name'], home=k == '1', neutral=True, us=us, them=them,
             box=f'https://fibalivestats.dcd.shared.geniussports.com/u/EYBL/{gid}/', video=url)
    if lines and us + them > 0:
        top = max(lines.items(), key=lambda kv: kv[1]['pts'])
        g.update(lines=lines, top=[top[0], top[1]['pts']], win=us > them)
    return g


async def main():
    st = load_state()
    st.setdefault('fbu', {}); st.setdefault('eybl', {}); st.setdefault('eybl20', {})
    async with async_playwright() as p:
        kw = {}
        if os.environ.get('HTTPS_PROXY'):
            kw = dict(proxy={'server': os.environ['HTTPS_PROXY']}, args=['--ignore-certificate-errors'])
        b = await p.chromium.launch(**kw)
        pg = await b.new_page(ignore_https_errors=True, user_agent=UA)
        # --- Higher League ---
        try:
            for gid, v in (await fbu_calendar(pg)).items():
                st['fbu'].setdefault(gid, {}).update({k: x for k, x in v.items() if x is not None})
        except Exception as e:
            print('calendar failed:', e)
        for gid, g in st['fbu'].items():
            if g.get('lines'):
                continue  # final box score already stored
            try:
                g.update({k: v for k, v in (await fbu_game(pg, gid)).items() if v is not None})
                print('fbu', gid, g.get('date'), g.get('us'), g.get('them'), len(g.get('lines', {})))
            except Exception as e:
                print('fbu game failed', gid, e)
        try:
            s = await fbu_standings(pg)
            if s:
                st['standings'] = s
        except Exception as e:
            print('standings failed:', e)
        # --- EYBL (U16 juniors + U20 senior squad) ---
        for key, team_url in EYBL_TEAMS:
          try:
            ids, urls = await eybl_matches(pg, team_url)
            for gid in ids:
                g = st[key].setdefault(gid, {'url': urls[gid]})
                if g.get('date'):
                    continue
                try:
                    await pg.goto(urls[gid], timeout=60000); await pg.wait_for_timeout(4000)
                    t = await pg.inner_text('body')
                    m = re.search(r'(\d{4})\.(\d\d)\.(\d\d),\s*(\d\d:\d\d)', t)
                    if m:
                        g['date'], g['time'] = f'{m.group(1)}-{m.group(2)}-{m.group(3)}', m.group(4)
                    v = re.search(r'\n([A-Z][A-Za-zăîșțâ\- ]+, [A-Z][a-z]+)\n', t)
                    if v:
                        g['venue'] = v.group(1)
                except Exception as e:
                    print('eybl match page failed', key, gid, e)
          except Exception as e:
            print('eybl team page failed:', key, e)
        await b.close()
    for key, _ in EYBL_TEAMS:
        for gid, g in st[key].items():
            if g.get('lines'):
                continue
            if g.get('date') and g['date'] > dt.date.today().isoformat():
                continue  # not played yet
            try:
                g.update(eybl_game(gid, g.get('url', '')))
                print(key, gid, g.get('us'), g.get('them'), len(g.get('lines', {})))
            except Exception as e:
                print('eybl game failed', key, gid, e)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, 'w'), ensure_ascii=False, indent=1)
    write_outputs(st)


def write_outputs(st):
    today = dt.date.today().isoformat()
    fbu = [dict(id=k, **v) for k, v in st['fbu'].items()]
    played = sorted([g for g in fbu if g.get('lines')], key=lambda g: g['date'])
    for g in played:
        g['box'] = f'{FBU}/game-{g["id"]}?season_id={SEASON}'
        g.setdefault('video', g['box'])
    upcoming = sorted([dict(date=g.get('date') if g.get('date') and g['date'] >= today else None, opp=g.get('opp', ''),
                            oppFull=g.get('oppFull', ''), home=g.get('home', True))
                       for g in fbu if not g.get('lines') and (not g.get('date') or g['date'] >= today)],
                      key=lambda u: (u['date'] is not None, u['date'] or ''))
    data = dict(league='Ukrainian Higher League', season='2026/27', updated=today, games=played, upcoming=upcoming,
                standings=st.get('standings', []), standingsUrl=f'{FBU}/standings?season_id={SEASON}')
    open(os.path.join(ROOT, 'games.js'), 'w').write('window.FUA_GAMES=' + json.dumps(data, ensure_ascii=False) + ';')
    eg = sorted([dict(id=k, **{x: y for x, y in v.items() if x != 'url'}) for k, v in st['eybl'].items() if v.get('lines')],
                key=lambda g: g.get('date', ''))
    edata = dict(league='EYBL U16', stage='EYBL U16 · Season 2026/27', season='2026/27', updated=today, games=eg, teamUrl=EYBL_TEAM)
    open(os.path.join(ROOT, 'eybl.js'), 'w').write('window.FUA_EYBL=' + json.dumps(edata, ensure_ascii=False) + ';')
    e20 = sorted([dict(id=k, **{x: y for x, y in v.items() if x not in ('url', 'id')}) for k, v in st.get('eybl20', {}).items() if v.get('lines')],
                 key=lambda g: g.get('date', ''))
    up20 = sorted([dict(id=k, date=v['date'], time=v.get('time', ''), city=(v.get('venue') or '').split(',')[0], opp=opp_from_url(v.get('url', '')))
                   for k, v in st.get('eybl20', {}).items() if not v.get('lines') and v.get('date') and v['date'] >= today],
                  key=lambda u: (u['date'], u['time']))
    d20 = dict(league='EYBL U20', stage='EYBL U20 · Season 2026/27', season='2026/27', updated=today, games=e20, upcoming=up20, teamUrl=EYBL20_TEAM)
    open(os.path.join(ROOT, 'eybl20.js'), 'w').write('window.FUA_EYBL20=' + json.dumps(d20, ensure_ascii=False) + ';')
    print('written', len(played), 'league games,', len(upcoming), 'upcoming,', len(eg), 'eybl games')


if __name__ == '__main__':
    asyncio.run(main())

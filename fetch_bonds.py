"""한국·미국·독일 국채 10년물 일별 금리와 원/달러·원/유로 매매기준율(서울외국환중개)을
받아 data/bond.json 으로 저장 (GitHub Actions에서 매일 실행).
공개 데이터만 다룹니다. 이 저장소에는 다른 데이터(Costar·RCA 등)를 절대 넣지 마세요."""
import csv, io, json, os, re, sys, urllib.request, datetime as dt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'bond.json')
KEY = os.environ.get('ECOS_KEY', '').strip()
DAYS = 60
today = dt.date.today()
start = today - dt.timedelta(days=DAYS)
UA = {'User-Agent': 'Mozilla/5.0 (sra-bond-fetch)'}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode('utf-8', 'replace')

def csv_rows(text):
    out = []
    for line in text.splitlines():
        m = re.match(r'^"?(\d{4}-\d{2}-\d{2})"?[;,]\s*"?(-?\d+(?:[.,]\d+)?)"?', line)
        if m:
            out.append([m.group(1), float(m.group(2).replace(',', '.'))])
    return out

def ecos(stat, item):
    if not KEY:
        raise RuntimeError('ECOS_KEY 비밀값이 설정되지 않음')
    u = (f'https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/1000/{stat}/D/'
         f'{start:%Y%m%d}/{today:%Y%m%d}/{item}')
    j = json.loads(get(u))
    if 'StatisticSearch' not in j:
        raise RuntimeError('ECOS 응답: ' + json.dumps(j.get('RESULT', j), ensure_ascii=False))
    out = []
    for r in j['StatisticSearch']['row']:
        t = str(r['TIME'])
        try:
            out.append([f'{t[:4]}-{t[4:6]}-{t[6:8]}', float(str(r['DATA_VALUE']).replace(',', ''))])
        except (TypeError, ValueError):
            pass
    return out

def kr():  return ecos('817Y002', '010210000')   # 시장금리(일별) 국고채 10년
def smbs(ccy):
    # 서울외국환중개 매매기준율 (엑셀 백데이터 Power Query와 같은 출처)
    t = get(f'http://www.smbs.biz/ExRate/StdExRate_xml.jsp?arr_value={ccy}_{start:%Y-%m-%d}_{today:%Y-%m-%d}')
    out = []
    for yy, mm, dd, v in re.findall(r"label='(\d{2})\.(\d{2})\.(\d{2})'[^>]*?value='([\d.,]+)'", t):
        out.append([f'20{yy}-{mm}-{dd}', float(v.replace(',', ''))])
    if not out:
        raise RuntimeError('서울외국환중개 응답 형식 오류')
    return out

def usd():
    try: return smbs('USD')
    except Exception: return ecos('731Y001', '0000001')   # 예비: 한국은행 ECOS 원/달러 매매기준율
def eur():
    try: return smbs('EUR')
    except Exception: return ecos('731Y001', '0000003')   # 예비: 한국은행 ECOS 원/유로 매매기준율

def treasury_year(y):
    # 미국 재무부 Daily Treasury Par Yield Curve Rates (10년 CMT) — FRED DGS10과 같은 값, 당일 저녁(미국시간) 게시
    t = get('https://home.treasury.gov/resource-center/data-chart-center/interest-rates/'
            f'daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve'
            f'&field_tdr_date_value={y}&page&_format=csv')
    rows = list(csv.reader(io.StringIO(t)))
    if not rows:
        return []
    head = [h.strip().strip('"').lower() for h in rows[0]]
    if '10 yr' not in head:
        raise RuntimeError('재무부 응답 형식 오류 (10 Yr 열 없음)')
    i = head.index('10 yr')
    out = []
    for r in rows[1:]:
        if len(r) <= i:
            continue
        m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', r[0].strip())
        try:
            v = float(r[i])
        except ValueError:
            continue
        if m:
            out.append([f'{m.group(3)}-{m.group(1)}-{m.group(2)}', v])
    return out

def us():
    try:
        out = []
        for y in range(start.year, today.year + 1):
            out += treasury_year(y)
        out = sorted(r for r in out if r[0] >= f'{start:%Y-%m-%d}')
        if out:
            return out
        raise RuntimeError('재무부 값 없음')
    except Exception:
        # 예비: FRED DGS10 (같은 시리즈, 금요일 값이 다음 주 화요일(한국시간)에 게시)
        return csv_rows(get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd={start:%Y-%m-%d}'))

def de():
    # 독일 연방은행: 10년 지표물(현재 발행된 10년 만기 연방채) 수익률 — Bloomberg 독일 10년물과 같은 기준
    # 전체 구간을 매번 통째로 받아 교체 (과거 값도 같은 시리즈로 통일)
    return csv_rows(get('https://api.statistiken.bundesbank.de/rest/data/BBSSY/'
                        'D.REN.EUR.A630.000000WT1010.A?format=csv&lang=en&startPeriod=1999-01-01'))

def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            old = {}
    res, err = {}, []
    for k, f in (('kr', kr), ('us', us), ('de', de), ('usd', usd), ('eur', eur)):
        try:
            rows = f()
            if not rows:
                raise RuntimeError('받은 값이 없음')
            res[k] = rows
        except Exception as e:
            err.append(f'{k}: {e}')
    data = {'t': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'err': err}
    # 독일은 전체 구간 보관 (받기 실패 시 직전 파일이 같은 시리즈일 때만 유지)
    if 'de' in res and len(res['de']) > 1000:
        data['de'] = sorted(res['de']); data['deSrc'] = 'WT1010'
    elif old.get('deSrc') == 'WT1010':
        data['de'] = old.get('de', []); data['deSrc'] = 'WT1010'
    for k in ('kr', 'us', 'de', 'usd', 'eur'):
        if k == 'de' and 'deSrc' in data:
            continue
        m = {d: v for d, v in old.get(k, [])}
        m.update({d: v for d, v in res.get(k, [])})
        data[k] = [[d, m[d]] for d in sorted(m)][-400:]      # 최근 400개 영업일만 보관
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, separators=(',', ':'))
    for k in ('kr', 'us', 'de', 'usd', 'eur'):
        last = data[k][-1] if data[k] else None
        print(k, 'OK' if k in res else 'FAIL', last)
    for e in err:
        print('ERROR', e)
    if len(err) == 5:
        sys.exit(1)

if __name__ == '__main__':
    main()

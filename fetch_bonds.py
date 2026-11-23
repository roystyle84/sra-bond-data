"""한국·미국·독일 국채 10년물 일별 금리를 받아 data/bond.json 으로 저장 (GitHub Actions에서 매일 실행).
공개 데이터만 다룹니다. 이 저장소에는 다른 데이터(Costar·RCA 등)를 절대 넣지 마세요."""
import json, os, re, sys, urllib.request, datetime as dt

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

def kr():
    if not KEY:
        raise RuntimeError('ECOS_KEY 비밀값이 설정되지 않음')
    u = (f'https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/1000/817Y002/D/'
         f'{start:%Y%m%d}/{today:%Y%m%d}/010210000')
    j = json.loads(get(u))
    if 'StatisticSearch' not in j:
        raise RuntimeError('ECOS 응답: ' + json.dumps(j.get('RESULT', j), ensure_ascii=False))
    out = []
    for r in j['StatisticSearch']['row']:
        t = str(r['TIME'])
        try:
            out.append([f'{t[:4]}-{t[4:6]}-{t[6:8]}', float(r['DATA_VALUE'])])
        except (TypeError, ValueError):
            pass
    return out

def us():
    return csv_rows(get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd={start:%Y-%m-%d}'))

def de():
    return csv_rows(get('https://api.statistiken.bundesbank.de/rest/data/BBSIS/'
                        'D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A'
                        f'?format=csv&lang=en&startPeriod={start:%Y-%m-%d}'))

def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            old = {}
    res, err = {}, []
    for k, f in (('kr', kr), ('us', us), ('de', de)):
        try:
            rows = f()
            if not rows:
                raise RuntimeError('받은 값이 없음')
            res[k] = rows
        except Exception as e:
            err.append(f'{k}: {e}')
    data = {'t': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'err': err}
    for k in ('kr', 'us', 'de'):
        m = {d: v for d, v in old.get(k, [])}
        m.update({d: v for d, v in res.get(k, [])})
        data[k] = [[d, m[d]] for d in sorted(m)][-400:]      # 최근 400개 영업일만 보관
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, separators=(',', ':'))
    for k in ('kr', 'us', 'de'):
        last = data[k][-1] if data[k] else None
        print(k, 'OK' if k in res else 'FAIL', last)
    for e in err:
        print('ERROR', e)
    if len(err) == 3:
        sys.exit(1)

if __name__ == '__main__':
    main()

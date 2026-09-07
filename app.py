import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('APP_SECRET_KEY', 'medpark-performance-local')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', '/app/user_data')
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, 'performance_data.json')
LOCK = threading.Lock()

BUSINESSES = ['덴탈', '메디컬', '에스테틱']
REGIONS = ['국내', '해외']
KINDS = ['기존', '신규']
STAGES = ['1차', '2차', '3차', '마감']
STATUSES = ['확정', '예상', '추진', '이월', '제외']
COUNT_STATUSES = {'확정', '예상', '추진'}


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def ensure_store():
    if os.path.exists(DATA_FILE):
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    raw = os.environ.get('INITIAL_DATA', '').strip()
    seed = json.loads(raw) if raw else {'actuals': {}, 'entries': [], 'comments': {}}
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def read_store():
    ensure_store()
    with LOCK:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)


def write_store(data):
    with LOCK:
        tmp = DATA_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def int_value(raw):
    try:
        return int(str(raw or '0').replace(',', '').strip() or 0)
    except ValueError:
        return 0


def money(v, blank='-'):
    if v is None:
        return blank
    return f"{int(v):,}"

app.jinja_env.filters['money'] = money


def actual_value(data, year, month, business, region, kind):
    key = f'{year}-{month:02d}|{business}|{region}|{kind}'
    return data.get('actuals', {}).get(key)


def matching_entries(data, year, month, stage, business, region, kind):
    return [e for e in data.get('entries', [])
            if e['year'] == year and e['month'] == month and e['stage'] == stage
            and e['business'] == business and e['region'] == region and e['kind'] == kind]


def snapshot(data, year, month, stage, business, region, kind):
    rows = matching_entries(data, year, month, stage, business, region, kind)
    if not rows:
        return {'has': False, 'confirmed': None, 'forecast': None, 'carryover': 0, 'excluded': 0, 'rows': []}
    confirmed = sum(e['amount'] for e in rows if e['status'] == '확정')
    forecast = sum(e['amount'] for e in rows if e['status'] in COUNT_STATUSES)
    carryover = sum(e['amount'] for e in rows if e['status'] == '이월')
    excluded = sum(e['amount'] for e in rows if e['status'] == '제외')
    return {'has': True, 'confirmed': confirmed, 'forecast': forecast, 'carryover': carryover, 'excluded': excluded, 'rows': rows}


def best_month(data, year, month, business, region, kind):
    av = actual_value(data, year, month, business, region, kind)
    if av is not None:
        return av
    for stage in ['마감', '3차', '2차', '1차']:
        s = snapshot(data, year, month, stage, business, region, kind)
        if s['has']:
            return s['forecast'] or 0
    return 0


def row_metrics(data, year, month, business, region, kind):
    hist = {m: actual_value(data, year, m, business, region, kind) or 0 for m in range(1, month)}
    ytd = sum(hist.values())
    avg = ytd / max(month - 1, 1)
    prev_ytd = sum(actual_value(data, year - 1, m, business, region, kind) or 0 for m in range(1, month))
    growth = ((ytd - prev_ytd) / prev_ytd) if prev_ytd else None
    cur = {stage: snapshot(data, year, month, stage, business, region, kind) for stage in STAGES}
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    nxt_month, nxt_year = (1, year + 1) if month == 12 else (month + 1, year)
    prev1 = snapshot(data, prev_year, prev_month, '1차', business, region, kind)
    prev3 = snapshot(data, prev_year, prev_month, '3차', business, region, kind)
    prev_close = snapshot(data, prev_year, prev_month, '마감', business, region, kind)
    next1 = snapshot(data, nxt_year, nxt_month, '1차', business, region, kind)
    q = (month - 1)//3 + 1
    qmonths = list(range((q-1)*3+1, q*3+1))
    qproj = sum(best_month(data, year, m, business, region, kind) for m in qmonths)
    q4 = sum(best_month(data, year, m, business, region, kind) for m in [10,11,12])
    second_half = sum(best_month(data, year, m, business, region, kind) for m in range(7,13))
    return {
        'business': business, 'region': region, 'kind': kind, 'hist': hist,
        'ytd': ytd, 'avg': avg, 'prev_ytd': prev_ytd, 'growth': growth,
        'prev_first': prev1['forecast'] if prev1['has'] else None,
        'prev_preclose': prev3['forecast'] if prev3['has'] else None,
        'prev_close': prev_close['forecast'] if prev_close['has'] else actual_value(data, prev_year, prev_month, business, region, kind),
        'first': cur['1차']['forecast'] if cur['1차']['has'] else None,
        'second': cur['2차']['forecast'] if cur['2차']['has'] else None,
        'third_confirmed': cur['3차']['confirmed'] if cur['3차']['has'] else None,
        'third_forecast': cur['3차']['forecast'] if cur['3차']['has'] else None,
        'close': cur['마감']['forecast'] if cur['마감']['has'] else actual_value(data, year, month, business, region, kind),
        'close_has': cur['마감']['has'] or actual_value(data, year, month, business, region, kind) is not None,
        'next_first': next1['forecast'] if next1['has'] else None,
        'carryover': cur['3차']['carryover'] if cur['3차']['has'] else 0,
        'qproj': qproj, 'q4proj': q4, 'second_half': second_half,
    }


def sum_rows(rows, label, business=None):
    def sum_nullable(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) if vals else None
    ytd = sum(r['ytd'] for r in rows)
    prev = sum(r['prev_ytd'] for r in rows)
    return {
        'is_total': True, 'is_grand': label.endswith('전체'), 'label': label,
        'business': business, 'region': '[소계]', 'kind': '',
        'hist': {m: sum(r['hist'].get(m, 0) for r in rows) for m in range(1,13)},
        'ytd': ytd, 'avg': sum(r['avg'] for r in rows), 'prev_ytd': prev,
        'growth': ((ytd-prev)/prev) if prev else None,
        'prev_first': sum_nullable('prev_first'), 'prev_preclose': sum_nullable('prev_preclose'),
        'prev_close': sum_nullable('prev_close'), 'first': sum_nullable('first'), 'second': sum_nullable('second'),
        'third_confirmed': sum_nullable('third_confirmed'), 'third_forecast': sum_nullable('third_forecast'),
        'close': sum_nullable('close'), 'close_has': all(r.get('close_has') for r in rows),
        'next_first': sum_nullable('next_first'), 'carryover': sum(r.get('carryover',0) for r in rows),
        'qproj': sum(r['qproj'] for r in rows), 'q4proj': sum(r['q4proj'] for r in rows),
        'second_half': sum(r['second_half'] for r in rows)
    }


def report_data(year, month):
    data = read_store()
    details, display = [], []
    for business in BUSINESSES:
        group = []
        for region in REGIONS:
            for kind in KINDS:
                row = row_metrics(data, year, month, business, region, kind)
                details.append(row); group.append(row); display.append(row)
        display.append(sum_rows(group, f'{business} 소계', business))
    grand = sum_rows(details, f'{year}년 전체')
    display.append(grand)
    top_key = f'{year}-{month:02d}'
    comments = data.get('comments', {}).get(top_key, {'top':'','bottom':'','updated_by':'','updated_at':''})
    parts = []
    for b in BUSINESSES:
        for r in REGIONS:
            part_rows = [x for x in details if x['business']==b and x['region']==r]
            done = all(x['close_has'] for x in part_rows)
            parts.append({'name': f'{b} {r}', 'done': done})
    close_done = sum(1 for p in parts if p['done'])
    third_total = grand['third_forecast']
    close_total = grand['close'] if grand['close_has'] else None
    diff = (close_total-third_total) if close_total is not None and third_total is not None else None
    err = (abs(diff)/third_total) if diff is not None and third_total else None
    return {'year':year,'month':month,'rows':display,'details':details,'comments':comments,'parts':parts,
            'close_done':close_done,'close_total':close_total,'third_total':third_total,'diff':diff,'error_rate':err,
            'prev_month':12 if month==1 else month-1,'next_month':1 if month==12 else month+1,'quarter':(month-1)//3+1}


@app.get('/')
def report():
    year = int(request.args.get('year', 2026))
    month = int(request.args.get('month', 8))
    capture = request.args.get('capture') == '1'
    return render_template('report.html', report=report_data(year, month), capture=capture)


@app.route('/input', methods=['GET', 'POST'])
def input_page():
    year = int(request.values.get('year', 2026)); month = int(request.values.get('month', 8))
    stage = request.values.get('stage', '3차'); business = request.values.get('business', '덴탈'); region = request.values.get('region', '국내')
    writer = request.values.get('writer', '').strip()
    if stage not in STAGES: stage='3차'
    if business not in BUSINESSES: business='덴탈'
    if region not in REGIONS: region='국내'
    if request.method == 'POST' and request.form.get('action') == 'add':
        if not writer:
            flash('작성자 이름을 입력하세요.', 'error')
        else:
            status = request.form.get('status','예상'); kind=request.form.get('kind','기존')
            if status not in STATUSES: status='예상'
            if stage == '마감': status='확정'
            if kind not in KINDS: kind='기존'
            amount=int_value(request.form.get('amount'))
            data=read_store(); data.setdefault('entries',[]).append({
                'id':str(uuid.uuid4()),'year':year,'month':month,'stage':stage,'business':business,'region':region,
                'kind':kind,'status':status,'item':request.form.get('item','').strip() or '미기재','amount':amount,
                'note':request.form.get('note','').strip(),'writer':writer,'updated_at':now_text(),'seeded':False
            }); write_store(data); flash('저장했습니다. 취합본에 바로 반영됩니다.','success')
        return redirect(url_for('input_page',year=year,month=month,stage=stage,business=business,region=region,writer=writer))
    data=read_store(); rows=[e for e in data.get('entries',[]) if e['year']==year and e['month']==month and e['stage']==stage and e['business']==business and e['region']==region]
    rows.sort(key=lambda x:(x['kind'],x['status'],x['writer'],x['item']))
    sums={s:sum(e['amount'] for e in rows if e['status']==s) for s in STATUSES}
    current=sum(e['amount'] for e in rows if e['status'] in COUNT_STATUSES)
    return render_template('input.html',year=year,month=month,stage=stage,business=business,region=region,writer=writer,
                           rows=rows,sums=sums,current=current,businesses=BUSINESSES,regions=REGIONS,stages=STAGES,statuses=STATUSES,kinds=KINDS)


@app.post('/entry/<entry_id>/edit')
def edit_entry(entry_id):
    data=read_store(); entry=next((e for e in data.get('entries',[]) if e['id']==entry_id),None)
    if not entry: return 'Not found',404
    entry['kind']=request.form.get('kind',entry['kind']) if request.form.get('kind') in KINDS else entry['kind']
    entry['status']=request.form.get('status',entry['status']) if request.form.get('status') in STATUSES else entry['status']
    if entry['stage'] == '마감': entry['status'] = '확정'
    entry['item']=request.form.get('item',entry['item']).strip() or '미기재'; entry['amount']=int_value(request.form.get('amount'))
    entry['note']=request.form.get('note','').strip(); entry['writer']=request.form.get('writer',entry['writer']).strip() or entry['writer']; entry['updated_at']=now_text(); entry['seeded']=False
    write_store(data); flash('수정했습니다.','success')
    return redirect(url_for('input_page',year=entry['year'],month=entry['month'],stage=entry['stage'],business=entry['business'],region=entry['region'],writer=entry['writer']))


@app.post('/entry/<entry_id>/delete')
def delete_entry(entry_id):
    data=read_store(); target=next((e for e in data.get('entries',[]) if e['id']==entry_id),None)
    if not target: return 'Not found',404
    data['entries']=[e for e in data['entries'] if e['id']!=entry_id]; write_store(data); flash('삭제했습니다.','success')
    return redirect(url_for('input_page',year=target['year'],month=target['month'],stage=target['stage'],business=target['business'],region=target['region']))


@app.post('/comments')
def save_comments():
    year=int(request.form.get('year',2026)); month=int(request.form.get('month',8)); writer=request.form.get('writer','').strip()
    data=read_store(); key=f'{year}-{month:02d}'; data.setdefault('comments',{})[key]={
        'top':request.form.get('top','').strip(),'bottom':request.form.get('bottom','').strip(),'updated_by':writer,'updated_at':now_text()}
    write_store(data); flash('회의 코멘트를 저장했습니다.','success'); return redirect(url_for('report',year=year,month=month))


@app.get('/health')
def health():
    return jsonify({'status':'ok','service':'medpark-performance-report'})

ensure_store()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT','8000')))

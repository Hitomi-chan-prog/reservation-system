"""実行: python tests/test_browser.py（検証環境のみPython Playwrightが必要）"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import json
import os
import re
from datetime import datetime, timezone, timedelta
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = next((ROOT / 'samples').glob('*.ics'))
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
    context = browser.new_context(timezone_id='America/Los_Angeles')
    page = context.new_page()
    errors = []
    passed = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(os.environ.get('TEST_URL', (ROOT / 'index.html').as_uri()))
    assert page.locator('#calendar-body td').count() == 90
    assert page.locator('td.reserved').count() == 2
    assert page.locator('td.busy').count() == 0
    page.locator('#ics-file').set_input_files(str(SAMPLE))
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('importedEvents.size === 300')
    events = page.evaluate('[...importedEvents.values()]')
    assert events[0]['start'] == 1782865800000 # 2026-07-01 09:30 JST
    assert events[0]['end'] == 1782869400000
    # サンプル全300件の開始・終了をPython側の独立した日時変換で照合
    source = SAMPLE.read_text()
    for field, key in [('DTSTART', 'start'), ('DTEND', 'end')]:
        values = re.findall(field + r';TZID=Asia/Tokyo:(\d{8}T\d{6})', source)
        assert len(values) == 300
        for item, value in zip(events, values):
            expected = datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=timezone(timedelta(hours=9)))
            assert item[key] == int(expected.timestamp() * 1000)

    page.evaluate('displayedMonday = new Date(Date.UTC(2026,5,29)); renderCalendar()')
    assert page.locator('td.busy').count() > 0
    assert page.locator('td button').count() > 0
    # 7/1 09:00空き、09:30・10:00予定あり、10:30空き
    assert page.locator('#calendar-body tr').nth(0).locator('td').nth(2).locator('button').count() == 1
    assert page.locator('#calendar-body tr').nth(1).locator('td').nth(2).get_attribute('class') == 'busy'
    assert page.locator('#calendar-body tr').nth(2).locator('td').nth(2).get_attribute('class') == 'busy'
    assert page.locator('#calendar-body tr').nth(3).locator('td').nth(2).locator('button').count() == 1
    page.locator('td.busy').first.click()
    assert not page.locator('dialog').evaluate('(e) => e.open')
    page.locator('td button').first.click()
    assert page.locator('dialog').evaluate('(e) => e.open')
    page.locator('.close-button').click()
    page.locator('#ics-file').set_input_files(str(SAMPLE))
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('importedEvents.size === 300')
    assert page.evaluate('importedEvents.size') == 300
    def event(uid, start='20260701T101500', end='20260701T111500', extra='', summary='検証'):
        return f'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:{uid}\nDTSTART:{start}\nDTEND:{end}\nSUMMARY:{summary}\n{extra}END:VEVENT\nEND:VCALENDAR\n'
    def file(name, source):
        return {'name': name, 'mimeType': 'text/calendar', 'buffer': source.encode()}
    page.locator('#ics-file').set_input_files([file('a.ics', event('a')), file('b.ics', event('b'))])
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('importedEvents.size === 302')
    page.locator('#ics-file').set_input_files(file('bad.ics', event('bad', extra='RRULE:FREQ=DAILY\n')))
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('document.getElementById("import-error").textContent.includes("RRULE")')
    assert page.evaluate('importedEvents.size') == 302
    page.locator('#ics-file').set_input_files(file('invalid.ics', 'invalid'))
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('document.getElementById("import-error").textContent.includes("VCALENDAR")')
    assert page.evaluate('importedEvents.size') == 302
    # ドラッグ＆ドロップ
    page.evaluate('''source => { const dt = new DataTransfer(); dt.items.add(new File([source], 'drop.ics', {type:'text/calendar'})); document.getElementById('drop-zone').dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles:true})); }''', event('drop'))
    page.wait_for_function('importedEvents.size === 303')
    page.evaluate('async () => { await importQueue; }')
    label = page.locator('#week-label').inner_text()
    page.locator('#next-week').click()
    assert page.locator('#week-label').inner_text() != label
    page.locator('#previous-week').click()
    assert page.locator('#week-label').inner_text() == label
    page.evaluate('displayedMonday = new Date(Date.UTC(2026,9,5)); renderCalendar()')
    assert page.locator('td.busy').count() > 0
    page.locator('#current-week').click()
    assert page.evaluate('displayedMonday.getTime() === Calendar.startOfWeek(Calendar.today()).getTime()')
    # 純粋な判定関数とパーサーの境界テスト（ブラウザTZは米国）
    results = page.evaluate(r'''() => {
      const wrap = body => `BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:test\n${body}\nEND:VEVENT\nEND:VCALENDAR`;
      const parse = body => ICSParser.parse(wrap(body))[0];
      const base = parse('DTSTART:20260701T101500\nDTEND:20260701T111500\nSUMMARY:安全\\,表示\\n折り返し\n 続き');
      const date = new Date(Date.UTC(2026,6,1));
      const states = [2,3,4,5].map(slot => Calendar.availability(date,slot,[base],[]).state);
      if (JSON.stringify(states) !== JSON.stringify(['busy','busy','busy','available'])) throw Error('partial overlap');
      const utc = parse('DTSTART:20260701T011500Z\nDTEND:20260701T021500Z');
      if (utc.start !== base.start || utc.end !== base.end) throw Error('UTC');
      if (base.summary !== '安全,表示\n折り返し続き') throw Error('text');
      const all = parse('DTSTART;VALUE=DATE:20260701\nDTEND;VALUE=DATE:20260702');
      if ([0,17].some(s => Calendar.availability(date,s,[all],[]).state !== 'busy')) throw Error('all day');
      if (Calendar.availability(new Date(Date.UTC(2026,6,2)),0,[all],[]).state !== 'available') throw Error('exclusive end');
      const overnight = parse('DTSTART:20260630T233000\nDTEND:20260701T093000');
      if (Calendar.availability(date,0,[overnight],[]).state !== 'busy' || Calendar.availability(date,1,[overnight],[]).state !== 'available') throw Error('overnight');
      const cancelled = {...all,status:'CANCELLED'};
      if (Calendar.availability(date,0,[cancelled],[]).state !== 'available') throw Error('cancelled');
      if (Calendar.availability(date,3,[base,utc],[]).busy.length !== 2) throw Error('overlapping events');
      for (const body of ['DTSTART;TZID=Europe/London:20260701T100000\nDTEND:20260701T110000','DTSTART:20260230T100000\nDTEND:20260301T110000','DTSTART:20260701T110000\nDTEND:20260701T100000']) {
        let failed = false; try { parse(body); } catch { failed = true; } if (!failed) throw Error('invalid accepted');
      }
      return states;
    }''')
    page.locator('#clear-files').click()
    assert page.evaluate('importedEvents.size') == 0
    assert page.locator('td.busy').count() == 0
    assert '未読み込み' in page.locator('#import-status').inner_text()
    passed.append('既存機能・300件・日時照合・重複判定・画面操作')

    def parse_ics(source):
        return page.evaluate('(source) => ICSParser.parse(source)', source)

    def reject_ics(source, expected):
        result = page.evaluate('''source => {
            try { ICSParser.parse(source); return {accepted: true}; }
            catch (error) { return {accepted: false, message: error.message}; }
        }''', source)
        assert not result['accepted'], source
        assert expected in result['message'], result

    def load(name, source):
        page.locator('#ics-file').set_input_files(file(name, source))
        page.evaluate('async () => { await importQueue; }')

    for encoded, decoded in [
        (r'C:\\work', 'C:\\work'),
        (r'backslash\\', 'backslash\\'),
        (r'literal\\n', 'literal\\n'),
        (r'a\nb\Nc\,d\;e', 'a\nb\nc,d;e'),
        ('普通の予定', '普通の予定'),
    ]:
        assert parse_ics(event('escape', summary=encoded))[0]['summary'] == decoded
    passed.append('正常エスケープ')
    for summary in [r'invalid\q', 'incomplete' + '\\']:
        reject_ics(event('invalid-escape', summary=summary), 'エスケープ')
    passed.append('不正エスケープ拒否')

    assert len(parse_ics(event('scale'))) == 1
    assert len(parse_ics(event('scale').replace('VERSION:2.0', 'VERSION:2.0\nCALSCALE:GREGORIAN'))) == 1
    for scale in ['JULIAN', '']:
        reject_ics(event('scale').replace('VERSION:2.0', 'VERSION:2.0\nCALSCALE:' + scale), '暦')
    passed.append('CALSCALE許可・拒否')

    for field in ['DTSTART', 'DTEND']:
        for param in ['TZID', 'VALUE']:
            reject_ics(event('empty-param').replace(field + ':', field + ';' + param + '="":'),
                       'タイムゾーン' if param == 'TZID' else '日時形式')
    floating = parse_ics(event('normal'))[0]
    tokyo = parse_ics(event('normal').replace('DTSTART:', 'DTSTART;TZID=Asia/Tokyo:').replace('DTEND:', 'DTEND;TZID=Asia/Tokyo:'))[0]
    explicit_type = parse_ics(event('normal').replace('DTSTART:', 'DTSTART;VALUE=DATE-TIME:').replace('DTEND:', 'DTEND;VALUE=DATE-TIME:'))[0]
    assert floating['start'] == tokyo['start'] == explicit_type['start']
    passed.append('空パラメーター拒否・正常日時維持')

    # 片側の引用符を拒否し、正常な引用・非引用形式は同じ日時に変換する。
    for field in ['DTSTART', 'DTEND']:
        for parameter in ['TZID=Asia/Tokyo"', 'TZID="Asia/Tokyo', 'VALUE=DATE-TIME"']:
            source = event('quote').replace(field + ':', field + ';' + parameter + ':')
            reject_ics(source, 'ICS構文')
        for parameter in ['TZID="Asia/Tokyo"', 'TZID=Asia/Tokyo', 'VALUE="DATE-TIME"']:
            parsed = parse_ics(event('quote').replace(field + ':', field + ';' + parameter + ':'))[0]
            assert parsed['start'] == floating['start']
            assert parsed['end'] == floating['end']
    passed.append('パラメーター引用符の許可・拒否')

    page.locator('#clear-files').click()
    load('update.ics', event('same', start='20260701T100000', end='20260701T103000'))
    original_start = page.evaluate('importedEvents.get("same").start')
    load('update.ics', event('same', start='20260701T140000', end='20260701T143000'))
    assert page.evaluate('importedEvents.size') == 1
    assert page.evaluate('importedEvents.get("same").start') == original_start + 4 * 3600000
    page.evaluate('displayedMonday = new Date(Date.UTC(2026,5,29)); renderCalendar()')
    assert page.locator('td.busy').count() == 1
    passed.append('同一UID日時更新')
    load('status.ics', event('same', start='20260701T140000', end='20260701T143000', extra='STATUS:CANCELLED\n'))
    assert page.evaluate('importedEvents.size') == 1
    assert page.evaluate('importedEvents.get("same").status') == 'CANCELLED'
    assert page.locator('td.busy').count() == 0
    load('status.ics', event('same', extra='STATUS:CONFIRMED\n'))
    assert page.evaluate('importedEvents.get("same").status') == 'CONFIRMED'
    assert page.locator('td.busy').count() == 3
    passed.append('同一UID状態更新')

    before = page.evaluate('JSON.stringify([...importedEvents])')
    files_before = page.evaluate('JSON.stringify([...importedFiles])')
    good = event('should-not-import')
    bad = event('bad-tail', extra='RRULE:FREQ=DAILY\n')
    combined = good.replace('END:VCALENDAR\n', '') + bad.split('VERSION:2.0\n', 1)[1]
    load('atomic.ics', combined)
    assert 'RRULE' in page.locator('#import-error').inner_text()
    assert page.evaluate('JSON.stringify([...importedEvents])') == before
    assert page.evaluate('JSON.stringify([...importedFiles])') == files_before
    passed.append('後続VEVENT不正時の全体取り消し')

    # 実際の時間を待たず、FileReaderの完了を手動制御して競合を再現。
    page.evaluate('''() => {
        window.NativeReader = window.FileReader;
        window.FileReader = class {
            readAsText(file) {
                window.pendingRead = {reader: this, file};
            }
        };
    }''')
    page.locator('#ics-file').set_input_files(file('pending.ics', event('stale')))
    page.wait_for_function('Boolean(window.pendingRead)')
    page.locator('#clear-files').click()
    assert page.evaluate('importedEvents.size === 0 && importedFiles.size === 0')
    page.evaluate('() => { window.FileReader = window.NativeReader; }')
    page.locator('#ics-file').set_input_files(file('fresh.ics', event('fresh')))
    page.evaluate('''async stale => {
        pendingRead.reader.result = stale;
        pendingRead.reader.onload();
        await importQueue;
    }''', event('stale'))
    assert page.evaluate('[...importedEvents.keys()]') == ['fresh']
    assert page.evaluate('[...importedFiles.keys()]') == ['fresh.ics']
    assert not page.locator('#import-error').inner_text()
    passed.append('読み込み途中クリア・再取り込み')

    page.locator('#clear-files').click()
    payload = '<img src=x onerror="window.icsXSS=true"><script>window.icsXSS=true</script>'
    load('xss.ics', event('xss', summary=payload))
    busy = page.locator('td.busy').first
    assert busy.get_attribute('title') == payload
    assert payload in busy.get_attribute('aria-label')
    assert page.locator('#calendar-body img, #calendar-body script').count() == 0
    assert page.evaluate('window.icsXSS === undefined')
    busy.click()
    assert not page.locator('dialog').evaluate('(element) => element.open')
    passed.append('ICS由来HTMLの安全な表示')
    page.locator('#clear-files').click()

    # 読込失敗を再現し正常データ保持
    page.locator('#ics-file').set_input_files(str(SAMPLE))
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('importedEvents.size === 300')
    page.evaluate('''() => { window.FileReader = class { readAsText() { this.onerror(); } }; }''')
    page.locator('#ics-file').set_input_files(file('read-fail.ics', event('fail')))
    page.evaluate('async () => { await importQueue; }')
    page.wait_for_function('document.getElementById("import-error").textContent.includes("読み込めません")')
    assert page.evaluate('importedEvents.size') == 300
    assert not errors, errors
    print(json.dumps({'sample_events': len(events), 'overlap_states': results, 'browser_errors': errors, 'passed': len(passed), 'failed': 0, 'test_groups': passed, 'result': 'PASS'}, ensure_ascii=False))
    browser.close()

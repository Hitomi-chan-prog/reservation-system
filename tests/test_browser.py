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
    assert page.locator('td.reserved').count() == 0
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
    assert not page.locator('#reservation-dialog').evaluate('(e) => e.open')
    page.locator('td button').first.click()
    assert page.locator('#reservation-dialog').evaluate('(e) => e.open')
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
    assert not page.locator('#reservation-dialog').evaluate('(element) => element.open')
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
    # STEP 3: 各テストで新しいブラウザコンテキストを使い保存領域を分離する。
    failures = []
    url = os.environ.get('TEST_URL', (ROOT / 'index.html').as_uri())
    empty_ics = 'BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n'

    def freeze(target):
        baseline = datetime(2026, 6, 29, tzinfo=timezone.utc)
        # install後のわずかな経過時間を吸収し、未来の基準時刻へ進めて停止する。
        target.clock.install(time=baseline - timedelta(days=1))
        target.clock.pause_at(baseline)

    def read_bookings(target):
        return target.evaluate('BookingStorage.read()')

    def load_ics(target, source=empty_ics, name='empty.ics'):
        target.locator('#ics-file').set_input_files(file(name, source))
        target.evaluate('async () => { await importQueue; }')

    def slot(target, index=2):
        return target.locator('#calendar-body tr').nth(index).locator('td').nth(0)

    def open_booking(target, index=2):
        slot(target, index).locator('button').click()
        target.locator('#customer-name').fill('  山田 花子  ')
        target.locator('#customer-email').fill('  hanako@example.com  ')

    def book(target, index=2):
        load_ics(target)
        open_booking(target, index)
        target.locator('#confirm-booking').click()
        assert not target.locator('#reservation-dialog').evaluate('(e) => e.open'), target.locator('#booking-error').inner_text()

    def run_booking_test(label, callback, timezone_id='America/Los_Angeles'):
        isolated = browser.new_context(timezone_id=timezone_id)
        target = isolated.new_page()
        page_errors = []
        isolated.on('page', lambda other: other.on('pageerror', lambda error: page_errors.append(str(error))))
        target.on('pageerror', lambda error: page_errors.append(str(error)))
        try:
            freeze(target)
            target.goto(url)
            callback(target, isolated)
            assert not page_errors, page_errors
            passed.append(label)
        except Exception as error:
            import traceback
            failures.append({'test': label, 'error': traceback.format_exc()})
        finally:
            errors.extend(page_errors)
            isolated.close()

    def registration(target, _):
        assert '予約はまだありません' in target.locator('#reservation-list').inner_text()
        book(target)
        saved = read_bookings(target)
        assert len(saved) == 1
        item = saved[0]
        assert item['name'] == '山田 花子' and item['email'] == 'hanako@example.com'
        assert item['end'] - item['start'] == 1800000
        assert item['status'] == 'confirmed' and item['cancelledAt'] is None
        assert item['id'] and item['createdAt'] == int(datetime(2026, 6, 29, tzinfo=timezone.utc).timestamp() * 1000)
        assert '予約を登録しました' in target.locator('#operation-status').inner_text()
        assert slot(target).get_attribute('class') == 'reserved'
        assert slot(target).locator('button').count() == 0
    run_booking_test('STEP3 予約登録・入力正規化・一覧即時反映', registration)

    def invalid_inputs(target, _):
        load_ics(target)
        open_booking(target)
        for name, email in [('', ''), ('   ', 'a@example.com'), ('a', ''), ('a', 'bad'), ('a' * 101, 'a@example.com'), ('a', 'a' * 243 + '@example.com')]:
            target.locator('#customer-name').fill(name)
            target.locator('#customer-email').fill(email)
            target.locator('#confirm-booking').click()
            assert target.locator('#booking-error').inner_text()
            assert not read_bookings(target)
        # 上限ちょうどは受理する。
        target.locator('#customer-name').fill('あ' * 100)
        target.locator('#customer-email').fill('a' * 242 + '@example.com')
        target.locator('#confirm-booking').click()
        assert len(read_bookings(target)) == 1
    run_booking_test('STEP3 必須・メール形式・100文字と254文字境界', invalid_inputs)

    def duplicate(target, _):
        book(target)
        result = target.evaluate('''() => {
            try { Reservations.register({...reservations[0],name:'他の人',email:'b@example.com',icsReady:true,events:[]}); return ''; }
            catch (error) { return error.message; }
        }''')
        assert '予約' in result and len(read_bookings(target)) == 1
    run_booking_test('STEP3 同一枠への再予約拒否', duplicate)

    def busy_slot(target, _):
        load_ics(target, event('busy', start='20260629T100000', end='20260629T103000'))
        assert slot(target).get_attribute('class') == 'busy'
        assert slot(target).locator('button').count() == 0
        slot(target).click()
        assert not target.locator('#reservation-dialog').evaluate('(e) => e.open')
        target.evaluate('openReservationDialog(dateAt(0),2)')
        target.locator('#customer-name').fill('a')
        target.locator('#customer-email').fill('a@example.com')
        target.locator('#confirm-booking').click()
        assert 'ICS予定' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
    run_booking_test('STEP3 ICS予定枠の表示・登録拒否', busy_slot)

    def unloaded(target, _):
        open_booking(target)
        assert target.locator('#confirm-booking').is_disabled()
        target.locator('#booking-form').evaluate('(form) => form.requestSubmit()')
        assert 'ICS' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
    run_booking_test('STEP3 ICS未読み込み時の確定拒否', unloaded)

    def past(target, _):
        load_ics(target)
        open_booking(target, 0) # 現在の9:00と同時
        target.locator('#confirm-booking').click()
        assert '開始済み' in target.locator('#booking-error').inner_text()
        target.locator('#dismiss-booking').click()
        target.locator('#previous-week').click()
        open_booking(target)
        target.locator('#confirm-booking').click()
        assert not read_bookings(target)
    run_booking_test('STEP3 過去・開始時刻一致の予約拒否', past)

    def recheck_ics(target, _):
        load_ics(target)
        open_booking(target)
        # ダイアログ表示後にICS更新。実際の読み込み処理を通す。
        target.evaluate('''source => showSelectedFiles([new File([source],'late.ics')])''', event('late', start='20260629T101500', end='20260629T104500'))
        target.evaluate('async () => { await importQueue; }')
        target.locator('#confirm-booking').click()
        assert 'ICS予定' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
    run_booking_test('STEP3 確定直前ICS再判定', recheck_ics)

    def recheck_storage(target, _):
        load_ics(target)
        open_booking(target)
        # storageイベントを待つ前でも、確定時の再読込で他予約を検出する。
        target.evaluate('''() => {
            const range=Calendar.slotRange(dateAt(0),2);
            BookingStorage.write([{id:'external',name:'別予約',email:'other@example.com',...range,status:'confirmed',createdAt:Date.now(),cancelledAt:null}]);
        }''')
        target.locator('#confirm-booking').click()
        assert '予約' in target.locator('#booking-error').inner_text()
        assert len(read_bookings(target)) == 1
        assert slot(target).get_attribute('class') == 'reserved'
    run_booking_test('STEP3 確定直前localStorage再判定', recheck_storage)

    def persistence(target, _):
        book(target)
        raw = target.evaluate('JSON.parse(localStorage.getItem(BookingStorage.key))')
        assert raw['version'] == 1 and len(raw['reservations']) == 1
        assert set(raw) == {'version', 'reservations'}
        target.reload()
        assert len(read_bookings(target)) == 1
        assert slot(target).get_attribute('class') == 'reserved'
        assert target.evaluate('importedEvents.size === 0 && importedFiles.size === 0')
        open_booking(target, 3)
        assert target.locator('#confirm-booking').is_disabled()
    run_booking_test('STEP3 保存・再読み込み復元・ICS再読込必須', persistence)

    def cancel_booking(target, _):
        book(target)
        target.locator('#reservation-list button').click()
        assert target.locator('#cancel-dialog').evaluate('(e) => e.open')
        assert '山田 花子' in target.locator('#cancel-detail').inner_text()
        target.locator('#dismiss-cancel').click()
        assert read_bookings(target)[0]['status'] == 'confirmed'
        target.locator('#reservation-list button').click()
        target.locator('#confirm-cancel').click()
        saved = read_bookings(target)[0]
        assert saved['status'] == 'cancelled' and saved['cancelledAt'] is not None
        assert slot(target).locator('button').count() == 1
        assert target.locator('#reservation-list button').count() == 0
        target.locator('#cancelled-tab').click()
        assert target.locator('#reservation-list button').count() == 0
        result = target.evaluate('''() => { try { Reservations.cancel(reservations[0].id); return ''; } catch(e) { return e.message; } }''')
        assert 'キャンセル済み' in result
        target.reload()
        assert read_bookings(target)[0]['status'] == 'cancelled'
        target.locator('#cancelled-tab').click()
        assert 'キャンセル済み' in target.locator('#reservation-list').inner_text()
    run_booking_test('STEP3 キャンセル確認・解除・再取消拒否・再読込保持', cancel_booking)

    def conflict(target, _):
        book(target)
        load_ics(target, event('conflict', start='20260629T100000', end='20260629T103000'))
        assert '競合' in target.locator('#conflict-warning').inner_text()
        assert read_bookings(target)[0]['status'] == 'confirmed'
        assert slot(target).get_attribute('class') == 'reserved'
        target.locator('#reservation-list button').click()
        target.locator('#confirm-cancel').click()
        assert slot(target).get_attribute('class') == 'busy'
    run_booking_test('STEP3 ICS競合警告・予約保護・取消後ICS枠維持', conflict)

    def corrupt_storage(target, _):
        for raw in ['not-json', '{"version":2,"reservations":[]}', '{"version":1,"reservations":[{}]}']:
            target.evaluate('raw => localStorage.setItem(BookingStorage.key,raw)', raw)
            target.reload()
            assert '不正' in target.locator('#storage-error').inner_text()
            load_ics(target)
            open_booking(target)
            target.locator('#confirm-booking').click()
            assert '不正' in target.locator('#booking-error').inner_text()
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
            assert not target.locator('#operation-status').inner_text()
            target.locator('#dismiss-booking').click()
    run_booking_test('STEP3 不正保存データ・未知バージョンを保護', corrupt_storage)

    def save_failure(target, _):
        load_ics(target)
        open_booking(target)
        target.evaluate('''() => { Storage.prototype.setItem = function() { throw new DOMException('full','QuotaExceededError'); }; }''')
        target.locator('#confirm-booking').click()
        assert '保存できません' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
        assert not target.locator('#operation-status').inner_text()
        assert slot(target).get_attribute('class') != 'reserved'
    run_booking_test('STEP3 容量不足時に成功扱いしない', save_failure)

    def denied_storage(target, _):
        target.evaluate('''() => { Storage.prototype.getItem = function() { throw new DOMException('denied','SecurityError'); }; }''')
        target.evaluate('reloadReservations()')
        assert 'アクセスできません' in target.locator('#storage-error').inner_text()
        load_ics(target)
        open_booking(target)
        target.locator('#confirm-booking').click()
        assert 'アクセスできません' in target.locator('#booking-error').inner_text()
        assert not target.locator('#operation-status').inner_text()
    run_booking_test('STEP3 localStorageアクセス拒否', denied_storage)

    def cancel_failure(target, _):
        book(target)
        target.locator('#reservation-list button').click()
        target.evaluate('''() => { Storage.prototype.setItem = function() { throw new Error('denied'); }; }''')
        target.locator('#confirm-cancel').click()
        assert '保存できません' in target.locator('#cancel-error').inner_text()
        assert read_bookings(target)[0]['status'] == 'confirmed'
        assert slot(target).get_attribute('class') == 'reserved'
    run_booking_test('STEP3 キャンセル保存失敗時の予約保持', cancel_failure)

    def tabs(target, isolated):
        other = isolated.new_page()
        freeze(other)
        other.goto(url)
        book(target)
        other.wait_for_function('reservations.length === 1')
        assert other.locator('td.reserved').count() == 1
        assert '山田 花子' in other.locator('#admin-reservation-list').inner_text()
        other.locator('#reservation-list button').click()
        other.locator('#confirm-cancel').click()
        target.wait_for_function('reservations[0].status === "cancelled"')
        assert target.locator('td.reserved').count() == 0
        assert 'キャンセル済み' in target.locator('#admin-reservation-list').inner_text()
        other.evaluate('localStorage.removeItem(BookingStorage.key)')
        target.wait_for_function('reservations.length === 0')
    run_booking_test('STEP3 実際の別タブstorageイベント・管理者更新', tabs)

    def admin_sort(target, _):
        book(target, 4)
        open_booking(target, 2)
        target.locator('#confirm-booking').click()
        target.locator('a[href="#admin"]').click()
        target.locator('#admin-view').wait_for(state='visible')
        assert '2件' in target.locator('#admin-reservation-count').inner_text()
        labels = target.locator('#admin-reservation-list strong').all_inner_texts()
        assert '10:00' in labels[0] and '11:00' in labels[1]
        assert '認証なし' in target.locator('#admin-view').inner_text()
        # 時間経過後も過去の予約が一覧に残る。
        target.clock.run_for(86400000)
        assert target.locator('#admin-reservation-list .reservation-card').count() == 2
    run_booking_test('STEP3 管理者一覧・日時順・過去予約表示', admin_sort)

    def xss_input(target, _):
        load_ics(target)
        open_booking(target)
        payload = '<img src=x onerror="window.bookingXSS=true">'
        target.locator('#customer-name').fill(payload)
        target.locator('#customer-email').fill('xss@example.com')
        target.locator('#confirm-booking').click()
        assert payload in target.locator('#reservation-list').inner_text()
        assert target.locator('#reservation-list img, #admin-reservation-list img').count() == 0
        assert target.evaluate('window.bookingXSS === undefined')
        open_booking(target, 3)
        target.locator('#customer-email').fill('<script>alert(1)</script>@example.com')
        target.locator('#confirm-booking').click()
        assert len(read_bookings(target)) == 1
        assert target.locator('#booking-error').inner_text()
        target.reload()
        assert target.evaluate('window.bookingXSS === undefined')
        assert payload in target.locator('#admin-reservation-list').inner_text()
    run_booking_test('STEP3 氏名XSS安全表示・不正メール拒否・復元時安全性', xss_input)

    def boundaries(target, _):
        result = target.evaluate('''() => {
            const d = new Date(Date.UTC(2026,5,29));
            return [0,17,18,-1].map(slot => {
                const range=Calendar.slotRange(d,slot);
                return Reservations.validRange(range.start,range.end);
            });
        }''')
        assert result == [True, True, False, False]
        assert not target.evaluate('''() => { const r=Calendar.slotRange(new Date(Date.UTC(2026,6,4)),2);return Reservations.validRange(r.start,r.end); }''')
        assert not target.evaluate('''() => { const r=Calendar.slotRange(dateAt(0),2);return Reservations.validRange(r.start+1,r.end+1); }''')
        # 17:30〜18:00は受理、翌枠と端が一致しても重複しない。
        book(target, 17)
        assert '17:30–18:00' in target.locator('#reservation-list').inner_text()
        assert slot(target, 16).locator('button').count() == 1
    run_booking_test('STEP3 営業時間・曜日・30分枠・終了境界', boundaries, 'Asia/Tokyo')

    def midnight(target, _):
        target.clock.run_for(15 * 3600000) # UTC15:00 = 東京の翌日0時
        assert target.evaluate('Calendar.today().toISOString()') == '2026-06-30T00:00:00.000Z'
        load_ics(target)
        open_booking(target)
        target.locator('#confirm-booking').click()
        assert '過去' in target.locator('#booking-error').inner_text()
        target.locator('#dismiss-booking').click()
        # 火曜9:00は未来なので受理。
        target.locator('#calendar-body tr').nth(0).locator('td').nth(1).locator('button').click()
        target.locator('#customer-name').fill('翌日')
        target.locator('#customer-email').fill('next@example.com')
        target.locator('#confirm-booking').click()
        assert '2026/06/30' in target.locator('#reservation-list').inner_text()
    run_booking_test('STEP3 東京の日付変更・ブラウザTZ差', midnight)

    def id_fallback(target, _):
        target.evaluate('''() => { Object.defineProperty(window.crypto,'randomUUID',{value:undefined,configurable:true}); }''')
        book(target)
        assert re.fullmatch(r'[0-9a-f]{32}', read_bookings(target)[0]['id'])
    run_booking_test('STEP3 randomUUIDなしの安全なID代替', id_fallback)

    def time_recheck(target, _):
        load_ics(target)
        open_booking(target)
        target.clock.run_for(3600000) # ダイアログ中に10:00へ
        target.locator('#confirm-booking').click()
        assert '開始済み' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
    run_booking_test('STEP3 ダイアログ中の時刻経過を確定時再判定', time_recheck)

    def invalid_records(target, _):
        book(target)
        saved = read_bookings(target)[0]
        bad_records = [
            [{**saved, 'start': saved['start'] + 1}],
            [{**saved, 'status': 'unknown'}],
            [{**saved, 'cancelledAt': 1}],
            [{**saved, 'createdAt': 'now'}],
            [saved, saved],
            [saved, {**saved, 'id': 'other'}],
        ]
        for records in bad_records:
            raw = json.dumps({'version': 1, 'reservations': records})
            target.evaluate('raw => localStorage.setItem(BookingStorage.key, raw)', raw)
            target.reload()
            assert '不正' in target.locator('#storage-error').inner_text()
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
    run_booking_test('STEP3 保存データの時刻・状態・ID重複・枠重複検証', invalid_records)

    def pending_import(target, _):
        load_ics(target)
        open_booking(target)
        target.evaluate('''() => {
            window.NativeReader=window.FileReader;
            window.FileReader=class { readAsText() {window.readerInFlight=this;} };
            showSelectedFiles([new File(['pending'],'pending.ics')]);
        }''')
        target.wait_for_function('Boolean(window.readerInFlight)')
        assert target.locator('#confirm-booking').is_disabled()
        target.locator('#booking-form').evaluate('(form) => form.requestSubmit()')
        assert 'ICS' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
        target.evaluate(r'''async () => {
            window.FileReader=window.NativeReader;
            readerInFlight.result='BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR';
            readerInFlight.onload();
            await importQueue;
        }''')
        assert target.locator('#confirm-booking').is_enabled()
    run_booking_test('STEP3 ICS読み込み中の確定禁止・完了後解除', pending_import)

    # ブラウザプロセスを終了し、同じ永続プロフィールで再起動する。
    # テスト後はプロフィールを削除し、個人情報・保存領域を残さない。
    import tempfile
    with tempfile.TemporaryDirectory(prefix='booking-browser-') as profile:
        restart_errors = []
        try:
            persistent = p.chromium.launch_persistent_context(profile, executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'], timezone_id='America/Los_Angeles')
            target = persistent.new_page()
            target.on('pageerror', lambda error: restart_errors.append(str(error)))
            freeze(target)
            target.goto(url)
            book(target)
            saved = read_bookings(target)
            persistent.close()
            persistent = p.chromium.launch_persistent_context(profile, executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'], timezone_id='Asia/Tokyo')
            target = persistent.new_page()
            target.on('pageerror', lambda error: restart_errors.append(str(error)))
            freeze(target)
            target.goto(url)
            assert read_bookings(target) == saved
            assert slot(target).get_attribute('class') == 'reserved'
            open_booking(target, 3)
            assert target.locator('#confirm-booking').is_disabled()
            assert not restart_errors, restart_errors
            passed.append('STEP3 ブラウザ終了・再起動後の永続復元')
        except Exception as error:
            failures.append({'test': 'STEP3 ブラウザ終了・再起動後の永続復元', 'error': str(error)})
        finally:
            persistent.close()
            errors.extend(restart_errors)

    def long_name_layout(target, _):
        payload = 'A' * 100
        load_ics(target)
        open_booking(target)
        target.locator('#customer-name').fill(payload)
        target.locator('#confirm-booking').click()
        assert not target.locator('#reservation-dialog').evaluate('(e) => e.open')
        assert read_bookings(target)[0]['name'] == payload
        assert payload in target.locator('#reservation-list .name').inner_text()
        reserved = target.locator('td.reserved')
        assert reserved.inner_text() == payload
        assert reserved.get_attribute('title') == payload
        assert payload in reserved.get_attribute('aria-label')
        for width in [1440, 390]:
            target.set_viewport_size({'width': width, 'height': 900})
            for route, container in [('#booking', '#reservation-list'), ('#admin', '#admin-reservation-list')]:
                target.evaluate('(route) => { location.hash = route; }', route)
                target.wait_for_function('(hash) => location.hash === hash && !document.getElementById(hash === "#admin" ? "admin-view" : "booking-view").hidden', arg=route)
                assert target.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), (width, route)
                assert target.locator(container + ' .name').evaluate('''name => {
                    const card = name.closest('.reservation-card');
                    const bounds = card.getBoundingClientRect();
                    const text = name.getBoundingClientRect();
                    return text.left >= bounds.left && text.right <= bounds.right &&
                        card.scrollWidth <= card.clientWidth && name.scrollWidth <= name.clientWidth;
                }'''), (width, route)
            target.evaluate('location.hash = "#booking"')
            target.wait_for_function('!document.getElementById("booking-view").hidden')
            assert reserved.evaluate('''cell => {
                const style = getComputedStyle(cell);
                return style.overflowX === 'hidden' && style.textOverflow === 'ellipsis' &&
                    style.whiteSpace === 'nowrap' && cell.scrollWidth > cell.clientWidth &&
                    cell.getBoundingClientRect().right <= cell.nextElementSibling.getBoundingClientRect().left + 1;
            }'''), width
        target.reload()
        assert read_bookings(target)[0]['name'] == payload
        assert payload in target.locator('td.reserved').get_attribute('aria-label')
    run_booking_test('STEP3 長い氏名100文字・1440px/390px・カード内折返し・枠省略・完全名保持', long_name_layout)

    def repeated_clock(target, isolated):
        for _ in range(10):
            another = isolated.new_page()
            try:
                freeze(another)
                assert another.evaluate('Date.now()') == int(datetime(2026, 6, 29, tzinfo=timezone.utc).timestamp() * 1000)
            finally:
                another.close()
    run_booking_test('STEP3 時計初期化10回反復', repeated_clock)

    def cancel_dialog_overflow(target, _):
        name = 'A' * 100
        email = 'a' * 242 + '@example.com'  # 最大254文字の正常な形式
        load_ics(target)
        open_booking(target)
        target.locator('#customer-name').fill(name)
        target.locator('#customer-email').fill(email)
        target.locator('#confirm-booking').click()
        assert not target.locator('#reservation-dialog').evaluate('(e) => e.open')
        for width in [390, 1440]:
            target.set_viewport_size({'width': width, 'height': 900})
            target.locator('#reservation-list button').click()
            dialog = target.locator('#cancel-dialog')
            assert dialog.evaluate('(e) => e.open')
            detail = target.locator('#cancel-detail')
            assert name in detail.inner_text() and email in detail.inner_text()
            assert detail.evaluate('''element => {
                const dialog = element.closest('dialog');
                const style = getComputedStyle(element);
                const range = document.createRange();
                range.selectNodeContents(element);
                const bounds = element.getBoundingClientRect();
                return style.overflowWrap === 'anywhere' && style.textOverflow !== 'ellipsis' &&
                    element.scrollWidth <= element.clientWidth && dialog.scrollWidth <= dialog.clientWidth &&
                    Array.from(range.getClientRects()).every(rect => rect.left >= bounds.left && rect.right <= bounds.right + 1);
            }'''), width
            assert target.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            # 確認画面を閉じても予約と保存内容は変わらない。
            before = read_bookings(target)
            target.locator('#dismiss-cancel').click()
            assert not dialog.evaluate('(e) => e.open')
            assert read_bookings(target) == before
            assert before[0]['status'] == 'confirmed'
        target.locator('#reservation-list button').click()
        target.locator('#confirm-cancel').click()
        assert not target.locator('#cancel-dialog').evaluate('(e) => e.open')
        saved = read_bookings(target)[0]
        assert saved['status'] == 'cancelled' and saved['cancelledAt'] is not None
        assert saved['name'] == name and saved['email'] == email
        assert slot(target).locator('button').count() == 1
    run_booking_test('STEP3 キャンセル確認の長い氏名・254文字メール・390px/1440px・中止と確定', cancel_dialog_overflow)


    # STEP 4: STEP 3形式のデータを画面から検索。保存文字列の不変性も検証する。
    def seed(target, count=41):
        return target.evaluate("""count => {
          const items = [];
          for (let day = 0; items.length < count; day++) {
            const date = new Date(Date.UTC(2026, 5, 29 + day));
            if ([0, 6].includes(date.getUTCDay())) continue;
            for (let slot = 0; slot < 18 && items.length < count; slot++) {
              const i = items.length;
              items.push({id: `step3-${i}`, name: i === 0 ? '山田 花子' : `利用者${i}`,
                email: i === 0 ? 'Hanako@Example.COM' : `user${i}@example.com`,
                ...Calendar.slotRange(date, slot), status: 'confirmed', createdAt: 1, cancelledAt: null});
            }
          }
          items.push({...Calendar.slotRange(new Date(Date.UTC(2026,5,29)), 0), createdAt: 1, email: 'history@example.com', ...items[0], id: 'history', name: '履歴の人', status: 'cancelled', cancelledAt: 1782691200000});
          const raw = JSON.stringify({version: 1, reservations: items});
          localStorage.setItem(BookingStorage.key, raw);
          reloadReservations();
          return raw;
        }""", count)

    def states(target, _):
        seed(target)
        assert target.locator('#confirmed-tab').inner_text() == '確定予約（41件）'
        assert target.locator('#cancelled-tab').inner_text() == 'キャンセル履歴（1件）'
        assert target.locator('#reservation-list .reservation-card').count() == 20
        assert '履歴の人' not in target.locator('#reservation-list').inner_text()
        target.locator('#cancelled-tab').click()
        assert target.locator('#reservation-list .reservation-card').count() == 1
        assert target.locator('#reservation-list button').count() == 0
        assert '2026/06/29' in target.locator('#reservation-list').inner_text()
        assert '09:00（日本時間）' in target.locator('#reservation-list').inner_text()
        target.locator('#cancelled-tab').press('ArrowLeft')
        assert target.locator('#confirmed-tab').get_attribute('aria-selected') == 'true'
        assert target.locator('#confirmed-tab').evaluate('(e) => e === document.activeElement')
    run_booking_test('STEP4 状態分離・タブ件数・履歴JST日時・参照専用・キーボード', states)

    for query, expected in [('山田', 1), (' Hanako@Example.COM ', 1), ('HANAKO', 1), ('user1@', 1), ('存在しない', 0), ('   ', 41)]:
        def search(target, _, query=query, expected=expected):
            raw = seed(target)
            target.locator('#booking-search').fill(query)
            assert f'全{expected}件中' in target.locator('#booking-range').inner_text()
            if expected == 0:
                assert '一致する予約はありません' in target.locator('#reservation-list').inner_text()
                assert target.locator('#booking-previous').is_disabled()
                assert target.locator('#booking-next').is_disabled()
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        run_booking_test(f'STEP4 部分一致・空白・大文字小文字・ゼロ件検索 {query!r}', search)

    def dates(target, _):
        seed(target)
        target.locator('#booking-date').fill('2026-06-30')
        assert '全18件中' in target.locator('#booking-range').inner_text()
        target.locator('#booking-search').fill('user2')
        assert '全10件中' in target.locator('#booking-range').inner_text()
        target.locator('#booking-clear-date').click()
        assert target.locator('#booking-date').input_value() == ''
        assert '全11件中' in target.locator('#booking-range').inner_text()
        target.locator('#booking-search').fill('')
        target.locator('#cancelled-tab').click()
        target.locator('#booking-date').fill('2026-06-29')
        assert '全1件中' in target.locator('#booking-range').inner_text()
        target.locator('#booking-date').fill('2026-06-30')
        assert '全0件中' in target.locator('#booking-range').inner_text()
        # JST日付境界を米国TZのブラウザ内で検証
        assert target.evaluate("ReservationList.dateKey(Date.parse('2026-06-28T15:00:00Z'))") == '2026-06-29'
    run_booking_test('STEP4 予約日・複合検索・日付クリア・履歴の元予約日・JST境界', dates)

    for count in [0, 20, 21, 40, 41]:
        def pagination(target, _, count=count):
            seed(target, count)
            pages = max(1, (count + 19) // 20)
            assert target.locator('#booking-page').inner_text() == f'1 / {pages}ページ'
            assert target.locator('#booking-previous').is_disabled()
            for number in range(1, pages + 1):
                assert target.locator('#reservation-list .reservation-card').count() == min(20, count - (number - 1) * 20)
                assert target.locator('#booking-page').inner_text() == f'{number} / {pages}ページ'
                if number < pages:
                    target.locator('#booking-next').click()
            assert target.locator('#booking-next').is_disabled()
            if pages > 1:
                target.locator('#booking-previous').click()
                assert target.locator('#booking-page').inner_text() == f'{pages-1} / {pages}ページ'
        run_booking_test(f'STEP4 ページ境界 {count}件', pagination)

    # 既存の境界テストに加え、画面の実データと表示範囲を独立した期待値で照合。
    for boundary_count in [20, 21, 40, 41]:
        for view in ['booking', 'admin']:
            def page_contents(target, _, count=boundary_count, view=view):
                seed(target, count)
                raw = target.evaluate('''() => {
                    const reversed = BookingStorage.read()
                        .filter(item => item.status === 'confirmed').reverse();
                    BookingStorage.write(reversed);
                    reloadReservations();
                    return localStorage.getItem(BookingStorage.key);
                }''')
                saved = json.loads(raw)['reservations']
                assert [item['id'] for item in saved] == [f'step3-{i}' for i in reversed(range(count))]
                target.evaluate('(hash) => { location.hash = hash; }', '#admin' if view == 'admin' else '#booking')
                target.locator('#admin-view' if view == 'admin' else '#booking-view').wait_for(state='visible')
                container = '#admin-reservation-list' if view == 'admin' else '#reservation-list'
                pages = (count + 19) // 20
                expected_names = ['山田 花子 様'] + [f'利用者{i} 様' for i in range(1, count)]
                seen = []
                assert target.locator(f'#{view}-previous').is_disabled()
                for number in range(1, pages + 1):
                    first = (number - 1) * 20
                    last = min(number * 20, count)
                    names = target.locator(container + ' .name').all_text_contents()
                    assert names == expected_names[first:last], (view, count, number, names)
                    assert target.locator(f'#{view}-range').inner_text() == f'全{count}件中 {first + 1}〜{last}件を表示'
                    assert target.locator(f'#{view}-page').inner_text() == f'{number} / {pages}ページ'
                    seen.extend(names)
                    if number < pages:
                        assert target.locator(f'#{view}-next').is_enabled()
                        target.locator(f'#{view}-next').click()
                assert seen == expected_names  # 全予約が日時順で表示され、欠落しない。
                assert len(seen) == len(set(seen)) == count  # ページ間の重複なし。
                assert target.locator(f'#{view}-next').is_disabled()
                if pages > 1:
                    target.locator(f'#{view}-previous').click()
                    first = (pages - 2) * 20
                    assert target.locator(container + ' .name').all_text_contents() == expected_names[first:first + 20]
                    assert target.locator(f'#{view}-range').inner_text() == f'全{count}件中 {first + 1}〜{first + 20}件を表示'
                assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
                assert read_bookings(target) == saved
            run_booking_test(f'STEP4 逆順保存・表示内容/範囲・重複/欠落なし {view} {boundary_count}件', page_contents)

    for view in ['booking', 'admin']:
        def history_dates(target, _, view=view):
            seed(target, 1)
            raw = target.evaluate('''() => {
                const items = BookingStorage.read();
                const history = items.find(item => item.status === 'cancelled');
                // JST 6/30 00:00は米国では6/29。ブラウザTZでの誤表示も検出する。
                history.cancelledAt = Date.parse('2026-06-29T15:00:00Z');
                BookingStorage.write(items);
                reloadReservations();
                return localStorage.getItem(BookingStorage.key);
            }''')
            history = next(item for item in json.loads(raw)['reservations'] if item['status'] == 'cancelled')
            jst = timezone(timedelta(hours=9))
            assert datetime.fromtimestamp(history['start'] / 1000, jst).date().isoformat() == '2026-06-29'
            assert datetime.fromtimestamp(history['cancelledAt'] / 1000, jst).date().isoformat() == '2026-06-30'
            target.evaluate('(hash) => { location.hash = hash; }', '#admin' if view == 'admin' else '#booking')
            target.locator('#admin-view' if view == 'admin' else '#booking-view').wait_for(state='visible')
            if view == 'admin':
                target.locator('#admin-status').select_option('cancelled')
            else:
                target.locator('#cancelled-tab').click()
            container = '#admin-reservation-list' if view == 'admin' else '#reservation-list'
            target.locator(f'#{view}-date').fill('2026-06-29')
            assert target.locator(container + ' .name').all_text_contents() == ['履歴の人 様']
            assert 'キャンセル日時：2026/06/30(火) 00:00（日本時間）' in target.locator(container).inner_text()
            target.locator(f'#{view}-search').fill('履歴')
            assert target.locator(container + ' .name').all_text_contents() == ['履歴の人 様']
            target.locator(f'#{view}-date').fill('2026-06-30')
            assert target.locator(container + ' .reservation-card').count() == 0
            assert '検索条件に一致する予約はありません' in target.locator(container).inner_text()
            assert target.locator(f'#{view}-range').inner_text() == '全0件中 0〜0件を表示'
            target.locator(f'#{view}-date').fill('2026-06-29')
            assert target.locator(container + ' .name').all_text_contents() == ['履歴の人 様']
            target.locator(f'#{view}-search').fill('山田')
            assert target.locator(container + ' .reservation-card').count() == 0
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        run_booking_test(f'STEP4 元予約日6/29・取消日6/30・氏名複合検索・JST {view}', history_dates)

    def reset(target, _):
        seed(target)
        target.locator('#booking-next').click()
        target.locator('#booking-search').fill('user')
        assert target.locator('#booking-page').inner_text().startswith('1 /')
        target.locator('#booking-next').click()
        target.locator('#booking-date').fill('2026-06-30')
        assert target.locator('#booking-page').inner_text().startswith('1 /')
        target.locator('#booking-clear-date').click()
        target.locator('#booking-next').click()
        target.locator('#cancelled-tab').click()
        assert target.locator('#booking-page').inner_text() == '1 / 1ページ'
    run_booking_test('STEP4 検索・日付・タブ変更でページリセット', reset)

    def update(target, _):
        seed(target, 21)
        target.locator('#booking-next').click()
        target.locator('#reservation-list button').click()
        target.locator('#confirm-cancel').click()
        assert target.locator('#booking-page').inner_text() == '1 / 1ページ'
        assert target.locator('#confirmed-tab').inner_text() == '確定予約（20件）'
        assert target.locator('#cancelled-tab').inner_text() == 'キャンセル履歴（2件）'
        target.locator('#cancelled-tab').click()
        assert target.locator('#reservation-list .reservation-card').count() == 2
    run_booking_test('STEP4 キャンセル後の件数・ページ縮小補正', update)

    def admin_filters(target, _):
        seed(target)
        target.goto(url + '#admin')
        assert '全42件（確定 41件・キャンセル 1件）' in target.locator('#admin-reservation-count').inner_text()
        assert target.locator('#admin-reservation-list .reservation-card').count() == 20
        target.locator('#admin-next').click()
        assert target.locator('#admin-page').inner_text() == '2 / 3ページ'
        target.locator('#admin-status').select_option('cancelled')
        assert target.locator('#admin-page').inner_text() == '1 / 1ページ'
        assert target.locator('#admin-reservation-list .reservation-card').count() == 1
        target.locator('#admin-status').select_option('confirmed')
        target.locator('#admin-search').fill(' HANAKO ')
        target.locator('#admin-date').fill('2026-06-29')
        assert '全1件中' in target.locator('#admin-range').inner_text()
        assert target.locator('#admin-reservation-list button').count() == 0
        target.locator('#admin-status').select_option('all')
        target.locator('#admin-search').fill('')
        target.locator('#admin-clear-date').click()
        assert '全42件中' in target.locator('#admin-range').inner_text()
    run_booking_test('STEP4 管理者状態別・検索・日付・ページ・全件数', admin_filters)

    def compatibility(target, _):
        raw = seed(target)
        original = read_bookings(target)
        before = target.evaluate('JSON.stringify(reservations)')
        target.evaluate("ReservationList.select(reservations, {query: 'user', page: 2})")
        assert target.evaluate('JSON.stringify(reservations)') == before
        target.reload()
        assert read_bookings(target) == original
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        target.locator('#cancelled-tab').click()
        assert '履歴の人' in target.locator('#reservation-list').inner_text()
    run_booking_test('STEP4 STEP3形式互換・再読み込み・配列/保存の非破壊性', compatibility)

    def layouts(target, _):
        seed(target)
        payload = '<img src=x onerror=window.listXSS=true>'
        target.evaluate("""payload => {
          reservations[0].name = payload;
          reservations[0].email = 'a'.repeat(64) + '@' + 'b'.repeat(63) + '.' + 'c'.repeat(63) + '.' + 'd'.repeat(60);
          reservations[1].name = '名'.repeat(100);
          renderReservations();
        }""", payload)
        for width in [1440, 390]:
            target.set_viewport_size({'width': width, 'height': 1000})
            for route in ['#booking', '#admin']:
                target.goto(url + route)
                target.wait_for_function("document.getElementById(location.hash === '#admin' ? 'admin-view' : 'booking-view').hidden === false")
                assert target.evaluate('document.documentElement.scrollWidth <= innerWidth')
                container = '#admin-reservation-list' if route == '#admin' else '#reservation-list'
                assert payload in target.locator(container).inner_text()
                assert target.locator(container + ' img').count() == 0
                assert target.evaluate('window.listXSS === undefined')
                assert target.locator(container + ' .email').first.evaluate('(e) => e.scrollWidth <= e.clientWidth')
                target.locator(container).scroll_into_view_if_needed()
                if os.environ.get('TEST_ARTIFACT_DIR'):
                    artifacts = Path(os.environ['TEST_ARTIFACT_DIR'])
                    artifacts.mkdir(parents=True, exist_ok=True)
                    target.screenshot(path=str(artifacts / f'step4-{width}-{route[1:]}.png'), full_page=True)
        target.goto(url + '#booking')
        target.locator('#booking-search').fill(payload)
        assert '全1件中' in target.locator('#booking-range').inner_text()
    run_booking_test('STEP4 長い氏名/メール・XSS・1440px/390px・両画面横幅', layouts)

    print(json.dumps({'sample_events': len(events), 'browser_errors': errors, 'passed': len(passed), 'failed': len(failures), 'test_groups': passed, 'failures': failures}, ensure_ascii=False))
    assert not failures, failures

    browser.close()

"""実行: python tests/test_browser.py（検証環境のみPython Playwrightが必要）"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import json
import os
import re
import csv
import io
import hashlib
from icalendar import Calendar as ExternalCalendar
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
        target.evaluate('openReservationDialog(dateAt(0),2)')
        result = target.evaluate('''() => {
            try { Reservations.register({...reservations[0],name:'他の人',email:'b@example.com',...bookingContext('booking')}); return ''; }
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

    # STEP 6: 未読み込み自体は禁止せず、未確認チェックなしの送信を拒否する。
    def unloaded(target, _):
        open_booking(target)
        assert target.locator('#confirm-booking').is_disabled()
        target.locator('#booking-form').evaluate('(form) => form.requestSubmit()')
        assert 'ICS' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
    run_booking_test('STEP3/6 ICS未読み込み・確認チェックなしの確定拒否', unloaded)

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

    # STEP 6: 再読み込み後も予約は保持し、外部未確認への同意だけを再取得する。
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
    run_booking_test('STEP3/6 保存・再読み込み復元・未確認同意リセット', persistence)

    def cancel_booking(target, _):
        book(target)
        target.locator('#reservation-list .cancel-reservation-button').click()
        assert target.locator('#cancel-dialog').evaluate('(e) => e.open')
        assert '山田 花子' in target.locator('#cancel-detail').inner_text()
        target.locator('#dismiss-cancel').click()
        assert read_bookings(target)[0]['status'] == 'confirmed'
        target.locator('#reservation-list .cancel-reservation-button').click()
        target.locator('#confirm-cancel').click()
        saved = read_bookings(target)[0]
        assert saved['status'] == 'cancelled' and saved['cancelledAt'] is not None
        assert slot(target).locator('button').count() == 1
        assert target.locator('#reservation-list .cancel-reservation-button').count() == 0
        target.locator('#cancelled-tab').click()
        assert target.locator('#reservation-list .cancel-reservation-button').count() == 0
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
        target.locator('#reservation-list .cancel-reservation-button').click()
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
        target.locator('#reservation-list .cancel-reservation-button').click()
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
        other.locator('#reservation-list .cancel-reservation-button').click()
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
            target.locator('#reservation-list .cancel-reservation-button').click()
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
        target.locator('#reservation-list .cancel-reservation-button').click()
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
        assert target.locator('#reservation-list .cancel-reservation-button').count() == 0
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
        target.locator('#reservation-list .cancel-reservation-button').click()
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


    # STEP 5: 登録ボタンの状態と日時変更。待機は読み込み・DOM・storage反映で同期する。
    def start_change(target, index=4):
        target.locator('#reservation-list .reschedule-button').first.click()
        assert target.locator('#reschedule-mode').is_visible()
        slot(target, index).locator('button').click()
        assert target.locator('#reschedule-dialog').evaluate('(e) => e.open')

    def rejected_change(target, **values):
        # 呼び出し引数でICS状態を偽装せず、現在の画面と状態から確認トークンを取得する。
        result = target.evaluate("""values => {
          if (values.events) values.events.forEach((event, i) => importedEvents.set(`reject-${i}`, event));
          if (values.icsStatus === 'unloaded') document.getElementById('clear-files').click();
          if (!rescheduleSnapshot) startReschedule(reservations[0].id);
          if (!document.getElementById('reschedule-dialog').open) openReservationDialog(dateAt(0),4);
          const range = { ...rescheduleRange, ...values };
          rescheduleRange = {start:range.start,end:range.end};
          try {
            Reservations.reschedule({snapshot: reservations[0], ...rescheduleRange, ...bookingContext('reschedule')});
            return '';
          } catch (error) { return error.message; }
        }""", values)
        assert result, values
        return result

    def ics_states(target, _):
        open_booking(target)
        assert target.locator('#confirm-booking').is_disabled()
        assert '未読み込み' in target.locator('#booking-hint').inner_text()
        target.locator('#dismiss-booking').click()
        load_ics(target, 'bad ICS', 'bad.ics')
        open_booking(target)
        assert target.locator('#confirm-booking').is_disabled()
        assert 'エラー' in target.locator('#booking-hint').inner_text()
        assert '予定を確認できませんでした' in target.locator('#ics-state').inner_text()
        # ダイアログが開いた状態でも非同期状態の変更が反映される。
        target.evaluate(r"showSelectedFiles([new File(['BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n'], 'ok.ics')])")
        target.evaluate('async () => { await importQueue; }')
        assert target.locator('#confirm-booking').is_enabled()
        assert '読み込み成功' in target.locator('#booking-hint').inner_text()
        target.evaluate("showSelectedFiles([new File(['bad'], 'bad-again.ics')])")
        target.evaluate('async () => { await importQueue; }')
        assert target.locator('#confirm-booking').is_disabled()
        assert target.evaluate('importedFiles.size') == 1
        target.locator('#dismiss-booking').click()
        target.locator('#clear-files').click()
        open_booking(target)
        assert target.locator('#confirm-booking').is_disabled()
        assert '未読み込み' in target.locator('#booking-hint').inner_text()
    run_booking_test('STEP5 ICS未読込・エラー・正常復帰・既存成功後失敗・クリアの案内', ics_states)

    def pending_states(target, _):
        load_ics(target)
        open_booking(target)
        target.evaluate("""() => {
            window.NativeReader = FileReader;
            window.FileReader = class {readAsText() { window.step5Reader = this; }};
            showSelectedFiles([new File(['pending'], 'pending.ics')]);
        }""")
        target.wait_for_function('Boolean(window.step5Reader)')
        assert target.locator('#confirm-booking').is_disabled()
        assert '読み込み中' in target.locator('#booking-hint').inner_text()
        target.evaluate(r"""async () => {
            step5Reader.result = 'BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n';
            step5Reader.onload(); await importQueue; window.FileReader = NativeReader;
        }""")
        assert target.locator('#confirm-booking').is_enabled()
        # 開いたダイアログを保持したままクリア（画面ではモーダルのため背後は操作不可）。
        target.evaluate("document.getElementById('clear-files').click()")
        assert target.locator('#confirm-booking').is_disabled()
        assert '未読み込み' in target.locator('#booking-hint').inner_text()
    run_booking_test('STEP5 ダイアログ中のICS保留・完了・クリアでボタン/理由更新', pending_states)

    for count in [16, 20]:
        def more_bookings(target, _, count=count):
            seed(target, count)
            target.evaluate("""() => {
                const current = BookingStorage.read().filter(item => item.status === 'confirmed');
                const history = {...current[0], status: 'cancelled', cancelledAt: Date.now()};
                BookingStorage.write([...current, ...Array.from({length: 7}, (_, i) => ({...history, id: `cancel-${i}`}))]);
                reloadReservations();
            }""")
            load_ics(target)
            # 既存予約がない火曜17:30を画面で選択する。
            target.locator('#calendar-body tr').nth(17).locator('td').nth(1).locator('button').click()
            target.locator('#customer-name').fill('追加の予約')
            target.locator('#customer-email').fill('new@example.com')
            assert target.locator('#confirm-booking').is_enabled()
            target.locator('#confirm-booking').click()
            data = read_bookings(target)
            assert len([item for item in data if item['status'] == 'confirmed']) == count + 1
            assert len([item for item in data if item['status'] == 'cancelled']) == 7
            assert not target.locator('#reservation-dialog').evaluate('(e) => e.open')
        run_booking_test(f'STEP5 キャンセル7件を保持し確定{count+1}件目を登録', more_bookings)

    def changed(target, _):
        book(target)
        before = read_bookings(target)[0]
        start_change(target)
        assert '10:00' in target.locator('#reschedule-before').inner_text()
        assert '11:00' in target.locator('#reschedule-after').inner_text()
        assert target.locator('#confirm-reschedule').is_enabled()
        target.locator('#confirm-reschedule').click()
        after = read_bookings(target)[0]
        assert after['start'] - before['start'] == 3600000
        assert after['end'] - after['start'] == 1800000
        for key in ['id', 'name', 'email', 'createdAt', 'status', 'cancelledAt']:
            assert after[key] == before[key]
        assert slot(target, 2).locator('button').count() == 1
        assert slot(target, 4).get_attribute('class') == 'reserved'
        assert '11:00' in target.locator('#reservation-list strong').inner_text()
        assert '11:00' in target.locator('#admin-reservation-list strong').inner_text()
        assert '変更し、保存しました' in target.locator('#operation-status').inner_text()
        target.reload()
        assert read_bookings(target)[0] == after
        assert slot(target, 4).get_attribute('class') == 'reserved'
    run_booking_test('STEP5 日時変更・ID/個人情報維持・新旧枠・管理者・再読込復元', changed)

    def same_slot(target, _):
        book(target)
        start_change(target, 2)
        assert target.locator('#confirm-reschedule').is_disabled()
        assert '同じ日時' in target.locator('#reschedule-hint').inner_text()
        item = read_bookings(target)[0]
        assert '同じ日時' in rejected_change(target, start=item['start'], end=item['end'])
        target.locator('#dismiss-reschedule').click()
        assert target.locator('#reschedule-mode').is_hidden()
    run_booking_test('STEP5 自身を除外・同じ日時は不要・中止で元予約保持', same_slot)

    for case in ['ICS', 'other', 'past', 'invalid', 'cancelled', 'unloaded']:
        def reject_destination(target, _, case=case):
            book(target)
            raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
            values = {}
            if case == 'ICS':
                values['events'] = [{'start': 1782698400000, 'end': 1782700200000, 'status': 'CONFIRMED'}] # 6/29 11:00 JST
            elif case == 'other':
                target.evaluate("""() => {
                    BookingStorage.write([...reservations, {...reservations[0], id: 'other', ...Calendar.slotRange(displayedMonday, 4)}]); reloadReservations();
                }""")
                raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
            elif case == 'past':
                values.update(start=1782432000000, end=1782433800000) # 6/26 09:00 JST
            elif case == 'invalid':
                values.update(start=1782698400001, end=1782700200001)
            elif case == 'cancelled':
                target.evaluate('reservations = Reservations.cancel(reservations[0].id); renderAll()')
                raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
                assert target.locator('#reservation-list .reschedule-button').count() == 0
                message = target.evaluate("""() => { try {Reservations.reschedule({snapshot:reservations[0],...Calendar.slotRange(displayedMonday,4)});return '';}catch(e){return e.message;} }""")
                assert 'キャンセル済み' in message
                assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
                return
            else:
                values['icsStatus'] = 'unloaded'
            rejected_change(target, **values)
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
            if case == 'other':
                target.locator('#dismiss-reschedule').click()
                target.locator('#reservation-list .reschedule-button').first.click()
                assert slot(target, 4).locator('button').count() == 0
        run_booking_test(f'STEP5 変更拒否・保存不変 {case}', reject_destination)

    def save_failure(target, _):
        book(target)
        original = read_bookings(target)
        start_change(target)
        target.evaluate("() => { Storage.prototype.setItem = () => { throw Error('quota'); }; }")
        target.locator('#confirm-reschedule').click()
        assert '保存できません' in target.locator('#reschedule-error').inner_text()
        assert read_bookings(target) == original
        assert not target.locator('#operation-status').inner_text()
        assert target.locator('#reschedule-dialog').evaluate('(e) => e.open')
    run_booking_test('STEP5 変更の保存失敗時に元データ保護・成功表示なし', save_failure)

    for operation in ['change', 'cancel']:
        def stale(target, context, operation=operation):
            book(target)
            start_change(target)
            other = context.new_page()
            freeze(other)
            other.goto(url)
            if operation == 'cancel':
                other.evaluate('Reservations.cancel(reservations[0].id)')
            else:
                start_change(other, 6)
                other.locator('#reschedule-external-ack').check()
                other.locator('#confirm-reschedule').click()
            target.wait_for_function('!Reservations.unchanged(reservations[0], rescheduleSnapshot)')
            assert target.locator('#confirm-reschedule').is_disabled()
            assert '別タブ' in target.locator('#reschedule-hint').inner_text()
            raw = other.evaluate('localStorage.getItem(BookingStorage.key)')
            # disabled制御を迂回しても保存前の再読込で古い上書きを拒否。
            message = target.evaluate("""() => { try {
                Reservations.reschedule({snapshot: rescheduleSnapshot, ...rescheduleRange, ...bookingContext('reschedule')}); return '';
            } catch(e) {return e.message;} }""")
            assert message
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        run_booking_test(f'STEP5 別タブ{operation}検出・古いsnapshotの上書き拒否', stale)

    def recheck(target, _):
        book(target)
        start_change(target)
        target.evaluate("""() => importedEvents.set('late', {...rescheduleRange, uid:'late', status:'CONFIRMED', summary:'後から予定'})""")
        target.locator('#confirm-reschedule').click()
        assert 'ICS予定' in target.locator('#reschedule-error').inner_text()
        assert '10:00' in target.locator('#reservation-list').inner_text()
        target.evaluate('importedEvents.clear()')
        target.clock.run_for(7200000)
        target.locator('#confirm-reschedule').click()
        assert '過去' in target.locator('#reschedule-error').inner_text()
    run_booking_test('STEP5 変更確定直前のICSと時刻の再判定', recheck)

    def list_update(target, _):
        seed(target, 21)
        load_ics(target)
        target.locator('#booking-date').fill('2026-06-30')
        target.locator('#booking-search').fill('user20')
        target.locator('#reservation-list .reschedule-button').click()
        target.locator('#calendar-body tr').nth(0).locator('td').nth(2).locator('button').click()
        target.locator('#confirm-reschedule').click()
        assert '全0件中' in target.locator('#booking-range').inner_text()
        assert target.locator('#confirmed-tab').inner_text() == '確定予約（21件）'
        target.locator('#booking-clear-date').click()
        assert '2026/07/01' in target.locator('#reservation-list').inner_text()
        assert target.locator('#booking-page').inner_text() == '1 / 1ページ'
        target.locator('#booking-search').fill('')
        target.locator('#booking-next').click()
        assert '利用者20' in target.locator('#reservation-list').inner_text()
    run_booking_test('STEP5 日時変更後の検索・件数・表示順・ページへの反映', list_update)

    def change_layout(target, _):
        book(target)
        name = '<img src=x onerror=window.step5XSS=true>' + 'A' * 55
        email = 'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 60
        target.evaluate("""values => { reservations[0].name=values[0]; reservations[0].email=values[1]; BookingStorage.write(reservations); renderAll(); }""", [name, email])
        for width in [1440, 390]:
            target.set_viewport_size({'width':width, 'height':1000})
            start_change(target)
            assert name in target.locator('#reschedule-before').inner_text()
            assert email in target.locator('#reschedule-before').inner_text()
            assert target.locator('#reschedule-dialog img').count() == 0
            assert target.evaluate('window.step5XSS === undefined')
            assert target.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert target.locator('#reschedule-dialog').evaluate('(e) => e.scrollWidth <= e.clientWidth')
            assert target.locator('#reschedule-before').evaluate('(e) => e.scrollWidth <= e.clientWidth')
            if os.environ.get('TEST_ARTIFACT_DIR'):
                target.screenshot(path=str(Path(os.environ['TEST_ARTIFACT_DIR']) / f'step5-change-{width}.png'))
            target.locator('#dismiss-reschedule').click()
            assert target.locator('#reschedule-mode').is_hidden()
        start_change(target)
        target.locator('#confirm-reschedule').focus()
        target.locator('#confirm-reschedule').press('Enter')
        assert not target.locator('#reschedule-dialog').evaluate('(e) => e.open')
        assert read_bookings(target)[0]['name'] == name
    run_booking_test('STEP5 長文・XSS・1440px/390pxの変更画面とキーボード確定', change_layout)


    def change_ics_state(target, _):
        book(target)
        start_change(target)
        target.evaluate("showSelectedFiles([new File(['bad'], 'bad.ics')])")
        target.evaluate('async () => { await importQueue; }')
        assert target.locator('#confirm-reschedule').is_disabled()
        assert 'エラー' in target.locator('#reschedule-hint').inner_text()
        target.evaluate(r"showSelectedFiles([new File(['BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR'], 'ok.ics')])")
        target.evaluate('async () => { await importQueue; }')
        assert target.locator('#confirm-reschedule').is_enabled()
        target.evaluate("document.getElementById('clear-files').click()")
        assert target.locator('#confirm-reschedule').is_disabled()
        assert '未読み込み' in target.locator('#reschedule-hint').inner_text()
        assert '10:00' in target.locator('#reservation-list').inner_text()
    run_booking_test('STEP5 変更確認中のICSエラー・正常復帰・クリア', change_ics_state)

    def clear_pending(target, _):
        load_ics(target)
        open_booking(target)
        target.evaluate("""() => {
            window.NativeReader = FileReader;
            window.FileReader = class { readAsText() { window.oldStep5Reader = this; } };
            showSelectedFiles([new File(['old'], 'old.ics')]);
        }""")
        target.wait_for_function('Boolean(window.oldStep5Reader)')
        target.evaluate("""() => {
            document.getElementById('clear-files').click();
            window.FileReader = NativeReader;
            showSelectedFiles([new File(['bad'], 'new-bad.ics')]);
        }""")
        assert target.locator('#confirm-booking').is_disabled()
        target.evaluate(r"""async () => {
            oldStep5Reader.result = 'BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR';
            oldStep5Reader.onload(); await importQueue;
        }""")
        assert target.evaluate('pendingImports') == 0
        assert target.evaluate('importedFiles.size') == 0
        assert target.locator('#confirm-booking').is_disabled()
        assert 'エラー' in target.locator('#booking-hint').inner_text()
    run_booking_test('STEP5 読み込み途中クリア・古い完了・後続エラーが状態を壊さない', clear_pending)

    def change_protection(target, _):
        seed(target, 1)
        load_ics(target)
        before = read_bookings(target)
        start_change(target)
        target.locator('#confirm-reschedule').click()
        after = read_bookings(target)
        assert after[1] == before[1]  # キャンセル履歴は一切変更しない。
        assert set(after[0]) == set(before[0])
        assert target.evaluate('JSON.parse(localStorage.getItem(BookingStorage.key)).version') == 1
        assert len(after) == len(before)
    run_booking_test('STEP5 STEP3/4形式・監査フィールド追加なし・キャンセル履歴保持', change_protection)

    def late_booking(target, _):
        book(target)
        start_change(target)
        target.evaluate("""() => {
            BookingStorage.write([...reservations, {...reservations[0], id:'late-booking', ...rescheduleRange}]);
        }""")
        raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
        target.locator('#confirm-reschedule').click()
        assert '予約がある' in target.locator('#reschedule-error').inner_text()
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
    run_booking_test('STEP5 変更確定直前の他予約を再読込して拒否', late_booking)

    def corrupt_change(target, _):
        book(target)
        start_change(target)
        target.evaluate("localStorage.setItem(BookingStorage.key, 'invalid')")
        target.locator('#confirm-reschedule').click()
        assert '不正' in target.locator('#reschedule-error').inner_text()
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == 'invalid'
        assert not target.locator('#operation-status').inner_text()
    run_booking_test('STEP5 変更時の不正保存データを上書きしない', corrupt_change)

    def blocked_calendar(target, _):
        book(target)
        load_ics(target, event('blocked-change', start='20260629T110000', end='20260629T113000'))
        target.locator('#reservation-list .reschedule-button').click()
        assert slot(target, 4).get_attribute('class') == 'busy'
        assert slot(target, 4).locator('button').count() == 0
        # 日付を過去へ移して変更モードでは空き枠ボタンも無効。
        target.locator('#previous-week').click()
        assert target.locator('#calendar-body td button:enabled').count() == 0
        target.locator('#stop-reschedule').click()
        assert read_bookings(target)[0]['status'] == 'confirmed'
    run_booking_test('STEP5 変更カレンダーのICS枠・過去枠は選択不可', blocked_calendar)


    # STEP 5レビュー修正: 再描画後のフォーカスと読み込み世代の独立性。
    def assert_focus(target, selector):
        assert target.locator(selector).evaluate('(e) => e === document.activeElement && e.getClientRects().length > 0')

    for action in ['stop', 'dismiss', 'escape', 'success']:
        def restored_focus(target, _, action=action):
            book(target)
            raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
            identity = read_bookings(target)[0]['id']
            if action == 'stop':
                target.locator('#reservation-list .reschedule-button').press('Enter')
                target.locator('#stop-reschedule').press('Enter')
            else:
                start_change(target)
                if action == 'escape':
                    target.locator('#reschedule-dialog').press('Escape')
                else:
                    target.locator('#confirm-reschedule' if action == 'success' else '#dismiss-reschedule').press('Enter')
            assert target.locator('#reschedule-mode').is_hidden()
            assert not target.locator('#reschedule-dialog').evaluate('(e) => e.open')
            assert_focus(target, '#reservation-list .reschedule-button')
            assert target.locator('#reservation-list .reschedule-button').get_attribute('data-reservation-id') == identity
            if action != 'success':
                assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
            target.locator('#reservation-list .reschedule-button').press('Tab')
            assert_focus(target, '#reservation-list .cancel-reservation-button')
        run_booking_test(f'STEP5修正 キーボード{action}後に対象カードへフォーカス復元', restored_focus)

    def filtered_focus(target, _):
        book(target)
        target.locator('#booking-date').fill('2026-06-29')
        target.locator('#reservation-list .reschedule-button').press('Enter')
        target.locator('#calendar-body tr').nth(4).locator('td').nth(1).locator('button').click()
        target.locator('#confirm-reschedule').press('Enter')
        assert target.locator('#reservation-list .reschedule-button').count() == 0
        assert '全0件中' in target.locator('#booking-range').inner_text()
        assert_focus(target, '#reservations-heading')
        target.locator('#reservations-heading').press('Tab')
        assert_focus(target, '#confirmed-tab')
    run_booking_test('STEP5修正 変更後に日付検索から消えたら一覧見出しへフォーカス', filtered_focus)

    def page_focus(target, _):
        seed(target, 21)
        target.evaluate("""() => {
            const items = BookingStorage.read();
            Object.assign(items[16], Calendar.slotRange(new Date(Date.UTC(2026, 6, 1)), 0));
            BookingStorage.write(items); reloadReservations();
        }""")
        load_ics(target)
        target.locator('#booking-next').click()
        target.locator('#reservation-list .reschedule-button').press('Enter')
        target.locator('#calendar-body tr').nth(16).locator('td').nth(0).locator('button').click()
        target.locator('#confirm-reschedule').press('Enter')
        # 最終ページの予約を空けておいた早い日時へ移す。非表示カードを追わない。
        assert target.locator('#booking-page').inner_text() == '2 / 2ページ'
        assert_focus(target, '#reservations-heading')
    run_booking_test('STEP5修正 並び替えで別ページへ移ったカードのフォーカス代替', page_focus)

    for delayed in ['load', 'error']:
        def clear_independent(target, _, delayed=delayed):
            load_ics(target)
            open_booking(target)
            raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
            target.evaluate("""() => {
                window.NativeReader = FileReader;
                window.readTasks = [];
                window.FileReader = class {
                    readAsText(file) {this.file = file; readTasks.push(this);}
                    abort() {this.aborted = true; this.onabort();}
                };
                showSelectedFiles([new File(['old'], 'old.ics'), new File(['skip'], 'skip.ics')]);
                window.oldQueue = importQueue;
            }""")
            target.wait_for_function('readTasks.length === 1')
            assert target.locator('#confirm-booking').is_disabled()
            target.evaluate("""() => {
                document.getElementById('clear-files').click();
                showSelectedFiles([new File(['first'], 'first.ics'), new File(['second'], 'second.ics')]);
            }""")
            # 古いonload/onerrorを通知する前に、新世代のFileReaderが開始する。
            target.wait_for_function('readTasks.length === 2')
            assert target.evaluate('readTasks[0].aborted === true')
            assert target.evaluate('readTasks.map(task => task.file.name)') == ['old.ics', 'first.ics']
            assert target.locator('#confirm-booking').is_disabled()
            target.evaluate("""delayed => {
                if (delayed === 'load') {readTasks[0].result='invalid stale ICS'; readTasks[0].onload();}
                else readTasks[0].onerror();
            }""", delayed)
            assert target.evaluate('pendingImports') == 1
            assert target.locator('#confirm-booking').is_disabled()
            target.evaluate('source => {readTasks[1].result=source; readTasks[1].onload();}', event('same', start='20260701T100000', end='20260701T103000'))
            target.wait_for_function('readTasks.length === 3')
            assert target.locator('#confirm-booking').is_disabled()
            target.evaluate('source => {readTasks[2].result=source; readTasks[2].onload();}', event('same', start='20260701T140000', end='20260701T143000'))
            target.evaluate('async () => {await importQueue; await oldQueue;}')
            assert target.evaluate('[...importedFiles.keys()]') == ['first.ics', 'second.ics']
            assert target.evaluate('importedEvents.size') == 1
            assert target.evaluate('importedEvents.get("same").start') == int(datetime(2026, 7, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
            assert target.locator('#confirm-booking').is_enabled()
            assert '読み込み成功' in target.locator('#booking-hint').inner_text()
            before = target.evaluate('JSON.stringify({events:[...importedEvents],files:[...importedFiles],pending:pendingImports})')
            target.evaluate("""() => {
                readTasks[0].onerror(); readTasks[0].result='stale'; readTasks[0].onload(); window.FileReader=NativeReader;
            }""")
            assert target.evaluate('JSON.stringify({events:[...importedEvents],files:[...importedFiles],pending:pendingImports})') == before
            assert target.locator('#confirm-booking').is_enabled()
            assert not target.locator('#import-error').inner_text()
            assert target.evaluate('activeReads.size') == 0
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        run_booking_test(f'STEP5修正 クリア直後の独立読込・abort・旧{delayed}・複数ファイル/UID・状態保護', clear_independent)

    def ui_labels(target, _):
        load_ics(target)
        open_booking(target)
        raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
        assert target.locator('#dismiss-booking').inner_text() == '入力をやめる'
        assert target.locator('.close-button').get_attribute('aria-label') == '入力をやめる'
        assert target.locator('#confirm-booking').inner_text() == '予約を確定する'
        target.locator('#dismiss-booking').press('Enter')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        open_booking(target)
        target.locator('#reservation-dialog').press('Escape')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        open_booking(target)
        target.locator('.close-button').press('Enter')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        book(target)
        raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
        start_change(target)
        assert target.locator('#dismiss-reschedule').inner_text() == '変更をやめる'
        assert target.locator('#stop-reschedule').inner_text() == '変更をやめる'
        assert target.locator('#confirm-reschedule').inner_text() == '変更を確定する'
        target.locator('#dismiss-reschedule').press('Enter')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        target.locator('#reservation-list .cancel-reservation-button').press('Enter')
        assert target.locator('#dismiss-cancel').inner_text() == '戻る'
        assert target.locator('#confirm-cancel').inner_text() == 'キャンセルを確定する'
        target.locator('#dismiss-cancel').press('Enter')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        target.locator('#reservation-list .cancel-reservation-button').press('Enter')
        target.locator('#cancel-dialog').press('Escape')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
    run_booking_test('STEP5修正 UI文言・×・Escape・中止操作の保存不変', ui_labels)


    # STEP 6: 未読み込みの明示同意と、読み込み中/エラーを区別する。
    def optional_book(target, index=2):
        open_booking(target, index)
        assert target.locator('#booking-external-warning').is_visible()
        target.locator('#booking-external-ack').check()
        assert target.locator('#confirm-booking').is_enabled()
        target.locator('#confirm-booking').click()
        assert not target.locator('#reservation-dialog').evaluate('(e) => e.open')

    def optional_registration(target, _):
        assert '保存済み予約のみ' in target.locator('#ics-state').inner_text()
        assert '重複する可能性' in target.locator('#ics-state').inner_text()
        open_booking(target)
        assert '確認チェックが必要' in target.locator('#booking-hint').inner_text()
        assert target.locator('#confirm-booking').is_disabled()
        target.locator('#booking-form').evaluate('(form) => form.requestSubmit()')
        assert '確認チェック' in target.locator('#booking-error').inner_text()
        assert not read_bookings(target)
        target.locator('#booking-external-ack').check()
        target.locator('#confirm-booking').click()
        saved = read_bookings(target)
        assert len(saved) == 1
        assert slot(target).get_attribute('class') == 'reserved'
        assert target.evaluate('importedFiles.size') == 0
        assert set(saved[0]) == {'id','name','email','start','end','status','createdAt','cancelledAt'}
        target.reload()
        assert read_bookings(target) == saved
        open_booking(target, 4)
        assert not target.locator('#booking-external-ack').is_checked()
        assert target.locator('#confirm-booking').is_disabled()
    run_booking_test('STEP6 ICSなしの入力・警告・同意前拒否・同意後登録・保存/復元互換', optional_registration)

    def reopen_ack(target, _):
        for action in ['dismiss', 'escape', 'cross']:
            open_booking(target)
            target.locator('#booking-external-ack').check()
            if action == 'escape': target.locator('#reservation-dialog').press('Escape')
            elif action == 'cross': target.locator('.close-button').click()
            else: target.locator('#dismiss-booking').click()
            assert not read_bookings(target)
            open_booking(target)
            assert not target.locator('#booking-external-ack').is_checked()
            assert target.locator('#confirm-booking').is_disabled()
            target.locator('#dismiss-booking').click()
        assert target.locator('#dismiss-booking').inner_text() == '入力をやめる'
    run_booking_test('STEP6 ダイアログ再表示で確認リセット・Esc/×/入力中止のデータ不変', reopen_ack)

    def optional_change(target, _):
        optional_book(target)
        before = read_bookings(target)[0]
        start_change(target)
        assert not target.locator('#reschedule-external-ack').is_checked()
        assert target.locator('#confirm-reschedule').is_disabled()
        assert '外部カレンダー' in target.locator('#reschedule-hint').inner_text()
        target.locator('#reschedule-external-ack').check()
        target.locator('#confirm-reschedule').click()
        after = read_bookings(target)[0]
        assert after == {**before, 'start': before['start']+3600000, 'end':before['end']+3600000}
        assert slot(target, 2).locator('button').count() == 1
        assert slot(target, 4).get_attribute('class') == 'reserved'
        assert_focus(target, '#reservation-list .reschedule-button')
        assert '11:00' in target.locator('#admin-reservation-list').inner_text()
        target.reload()
        assert read_bookings(target)[0] == after
    run_booking_test('STEP6 ICSなしの日時変更・独立した同意・新旧枠・管理者・復元', optional_change)

    def separate_ack(target, _):
        optional_book(target)
        start_change(target)
        target.locator('#reschedule-external-ack').check()
        raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
        target.locator('#reschedule-dialog').press('Escape')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        start_change(target)
        assert not target.locator('#reschedule-external-ack').is_checked()
        assert target.locator('#confirm-reschedule').is_disabled()
        target.locator('#dismiss-reschedule').click()
        open_booking(target, 6)
        assert not target.locator('#booking-external-ack').is_checked()
        assert target.locator('#confirm-booking').is_disabled()
    run_booking_test('STEP6 登録/変更の同意非共有・変更再表示でリセット', separate_ack)

    for prefix in ['booking','reschedule']:
        def state_changes(target, _, prefix=prefix):
            if prefix == 'reschedule':
                optional_book(target)
                start_change(target)
            else: open_booking(target)
            checkbox = target.locator(f'#{prefix}-external-ack')
            confirm = target.locator(f'#confirm-{prefix}')
            checkbox.check()
            assert confirm.is_enabled()
            target.evaluate("""() => {
                window.NativeReader=FileReader;
                window.FileReader=class {readAsText(){window.optionalReader=this;} abort(){this.onabort();}};
                showSelectedFiles([new File(['pending'],'pending.ics')]);
            }""")
            target.wait_for_function('Boolean(window.optionalReader)')
            assert confirm.is_disabled()
            assert not checkbox.is_checked()
            assert '読み込み中' in target.locator(f'#{prefix}-hint').inner_text()
            raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
            # disabledを迂回しても、現在の状態を保存直前に再検証する。
            if prefix == 'booking': target.locator('#booking-form').evaluate('(form) => form.requestSubmit()')
            else: confirm.evaluate('(button) => button.dispatchEvent(new MouseEvent("click"))')
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
            target.evaluate("optionalReader.onerror()")
            target.evaluate('async()=>{await importQueue;}')
            assert confirm.is_disabled()
            assert 'エラー' in target.locator(f'#{prefix}-hint').inner_text()
            assert not checkbox.is_checked()
            target.evaluate("""() => {
                window.FileReader=NativeReader;
                document.getElementById('clear-files').click();
            }""")
            assert target.locator(f'#{prefix}-external-warning').is_visible()
            assert not checkbox.is_checked()
            assert confirm.is_disabled()
            checkbox.check()
            assert confirm.is_enabled()
            # 同じ未読み込み状態への再クリアでも、前の同意を使わない。
            target.evaluate("document.getElementById('clear-files').click()")
            assert not checkbox.is_checked()
            assert confirm.is_disabled()
            checkbox.check()
            target.evaluate('source => showSelectedFiles([new File([source], "ok.ics")])', empty_ics)
            target.evaluate('async()=>{await importQueue;}')
            assert target.locator(f'#{prefix}-external-warning').is_hidden()
            assert not checkbox.is_checked()
            assert confirm.is_enabled()
            assert '最新性は保証' in target.locator(f'#{prefix}-hint').inner_text()
            target.evaluate("document.getElementById('clear-files').click()")
            assert target.locator(f'#{prefix}-external-warning').is_visible()
            assert confirm.is_disabled()
        run_booking_test(f'STEP6 {prefix}の読込中/エラー/クリア/成功と同意リセット・確定競合', state_changes)

    for state in ['loading','error','unloaded','invalid']:
        def domain_policy(target, _, state=state):
            optional_book(target)
            raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
            messages = target.evaluate("""state => {
                if(state === 'loading') pendingImports=1;
                if(state === 'error') importFailed=true;
                openReservationDialog(dateAt(0),4);
                const booking = state === 'invalid' ? {context:{}} : bookingContext('booking');
                let first;
                try {Reservations.register({...selectedRange,name:'検証',email:'test@example.com',...booking});first='';}catch(e){first=e.message;}
                document.getElementById('reservation-dialog').close();
                startReschedule(reservations[0].id);openReservationDialog(dateAt(0),4);
                const change = state === 'invalid' ? {context:{}} : bookingContext('reschedule');
                let second;
                try {Reservations.reschedule({snapshot:rescheduleSnapshot,...rescheduleRange,...change});second='';}catch(e){second=e.message;}
                return [first,second];
            }""", state)
            assert all(messages), messages
            assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
        run_booking_test(f'STEP6 保存処理がICS状態/同意を再検証 {state}', domain_policy)

    for operation in ['register','change']:
        for reason in ['overlap','past']:
            def optional_reject(target, _, operation=operation, reason=reason):
                optional_book(target)
                raw = target.evaluate('localStorage.getItem(BookingStorage.key)')
                message = target.evaluate("""args => {
                    const range=args.reason==='past' ? Calendar.slotRange(new Date(Date.UTC(2026,5,26)),0) : {start:reservations[0].start,end:reservations[0].end};
                    if (args.operation==='change') {
                        const second={...reservations[0],id:'second',...Calendar.slotRange(displayedMonday,6)};
                        BookingStorage.write([...reservations,second]);reloadReservations();
                        startReschedule(second.id);
                        openReservationDialog(dateAt(0),4);
                        rescheduleRange=range;
                        document.getElementById('reschedule-external-ack').checked=true;
                        try {Reservations.reschedule({...range,snapshot:second,...bookingContext('reschedule')});return '';}catch(e){return e.message;}
                    }
                    openReservationDialog(dateAt(0),4);
                    selectedRange=range;
                    document.getElementById('booking-external-ack').checked=true;
                    try {Reservations.register({...range,name:'追加',email:'add@example.com',...bookingContext('booking')});return '';}catch(e){return e.message;}
                }""", {'operation':operation,'reason':reason})
                assert '過去' in message if reason == 'past' else '予約がある' in message
                if operation == 'register':
                    assert target.evaluate('localStorage.getItem(BookingStorage.key)') == raw
                else:
                    assert read_bookings(target)[0] == json.loads(raw)['reservations'][0]
                    assert read_bookings(target)[1]['start'] == int(datetime(2026,6,29,3,tzinfo=timezone.utc).timestamp()*1000)
            run_booking_test(f'STEP6 ICSなしでも{operation}の{reason}を拒否', optional_reject)

    def partial_error(target, _):
        open_booking(target)
        target.locator('#booking-external-ack').check()
        target.locator('#dismiss-booking').click()
        load_ics(target)
        # 同時にキューへ追加した一部が失敗しても、後続成功でエラーを隠さない。
        target.evaluate("""sources => {
            showSelectedFiles([new File([sources[0]],'good.ics'),new File(['bad'],'bad.ics')]);
            showSelectedFiles([new File([sources[1]],'queued.ics')]);
        }""", [event('partial'), empty_ics])
        target.evaluate('async()=>{await importQueue;}')
        open_booking(target)
        assert 'エラー' in target.locator('#booking-hint').inner_text()
        assert 'bad.ics' in target.locator('#import-error').inner_text()
        assert target.locator('#confirm-booking').is_disabled()
        assert target.locator('#booking-external-warning').is_hidden()
        target.locator('#dismiss-booking').click()
        load_ics(target)
        open_booking(target)
        assert target.locator('#confirm-booking').is_enabled()
        assert target.locator('#booking-external-warning').is_hidden()
    run_booking_test('STEP6 追加/複数ICSの部分失敗・後続成功でエラーを隠さず正常再読込で復帰', partial_error)

    for count in [16,20]:
        def optional_many(target, _, count=count):
            seed(target,count)
            target.locator('#calendar-body tr').nth(17).locator('td').nth(1).locator('button').click()
            target.locator('#customer-name').fill('ICSなし追加')
            target.locator('#customer-email').fill('optional@example.com')
            target.locator('#booking-external-ack').check()
            target.locator('#confirm-booking').click()
            assert len([r for r in read_bookings(target) if r['status']=='confirmed'])==count+1
            if count == 20:
                target.locator('#booking-next').click()
                assert target.locator('#booking-page').inner_text()=='2 / 2ページ'
                assert 'ICSなし追加' in target.locator('#reservation-list').inner_text()
        run_booking_test(f'STEP6 ICSなしで{count+1}件目登録・確定ページ表示', optional_many)

    def cancelled_pages(target, _):
        seed(target,21)
        target.evaluate("""()=>{
            const items=BookingStorage.read().filter(item=>item.status==='confirmed').map(item=>({...item,status:'cancelled',cancelledAt:Date.now()}));
            BookingStorage.write(items);reloadReservations();
        }""")
        target.locator('#cancelled-tab').click()
        assert target.locator('#reservation-list .reservation-card').count()==20
        target.locator('#booking-next').click()
        assert target.locator('#booking-page').inner_text()=='2 / 2ページ'
        assert '全21件中 21〜21件を表示' in target.locator('#booking-range').inner_text()
        assert '利用者20' in target.locator('#reservation-list').inner_text()
        assert target.locator('#reservation-list button').count()==0
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        target.reload()
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        assert len(read_bookings(target))==21
    run_booking_test('STEP6 キャンセル履歴21件のページ・参照専用・再読込保持', cancelled_pages)

    for operation in ['booking','reschedule']:
        def optional_storage_failure(target, _, operation=operation):
            if operation == 'reschedule':
                optional_book(target)
                start_change(target)
            else: open_booking(target)
            raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
            target.locator(f'#{operation}-external-ack').check()
            target.evaluate("() => {Storage.prototype.setItem=()=>{throw Error('quota');};}")
            target.locator(f'#confirm-{operation}').click()
            assert '保存できません' in target.locator(f'#{operation}-error').inner_text()
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
            assert not target.locator('#operation-status').inner_text()
        run_booking_test(f'STEP6 ICSなし{operation}の保存失敗で元データ保護', optional_storage_failure)

    def optional_layout(target, _):
        optional_book(target)
        payload='<img src=x onerror=window.optionalXSS=true>'+'A'*45
        target.evaluate("""name=>{reservations[0].name=name;BookingStorage.write(reservations);renderAll();}""",payload)
        for width in [1440,390]:
            target.set_viewport_size({'width':width,'height':1000})
            open_booking(target,6)
            assert target.locator('#booking-external-warning').is_visible()
            target.locator('#booking-external-ack').focus()
            target.locator('#booking-external-ack').press('Space')
            assert target.locator('#confirm-booking').is_enabled()
            assert target.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert target.locator('#reservation-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            assert target.locator('#booking-external-warning').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            if os.environ.get('TEST_ARTIFACT_DIR'):
                target.screenshot(path=str(Path(os.environ['TEST_ARTIFACT_DIR'])/f'step6-booking-{width}.png'))
            target.locator('#reservation-dialog').press('Escape')
            start_change(target)
            assert payload in target.locator('#reschedule-before').inner_text()
            assert target.locator('#reschedule-dialog img').count()==0
            assert target.evaluate('window.optionalXSS===undefined')
            assert target.locator('#reschedule-external-warning').is_visible()
            assert target.locator('#reschedule-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            if os.environ.get('TEST_ARTIFACT_DIR'):
                target.screenshot(path=str(Path(os.environ['TEST_ARTIFACT_DIR'])/f'step6-change-{width}.png'))
            target.locator('#reschedule-external-ack').focus()
            target.locator('#reschedule-external-ack').press('Space')
            assert target.locator('#confirm-reschedule').is_enabled()
            target.locator('#reschedule-dialog').press('Escape')
            assert_focus(target,'#reservation-list .reschedule-button')
        assert read_bookings(target)[0]['name']==payload
    run_booking_test('STEP6 未確認チェック/警告の1440px/390px・Space/Esc・フォーカス・XSS', optional_layout)


    # Medium回帰: 呼び出し側の状態/同意ではなく、現在の操作に結び付いたトークンを検証。
    def prepare_context(target, prefix):
        seed(target,1)
        if prefix=='booking': open_booking(target,4)
        else: start_change(target)
        target.locator(f'#{prefix}-external-ack').check()
        target.evaluate("""prefix=>{
            window.heldContext=bookingContext(prefix);
            window.heldOptions={...(prefix==='booking'?selectedRange:rescheduleRange)};
            if(prefix==='reschedule') heldOptions.snapshot={...rescheduleSnapshot};
        }""",prefix)

    def direct_save(target, prefix, fresh=False):
        return target.evaluate("""args=>{
            const options={...heldOptions,name:'直接登録',email:'direct@example.com',
                ...(args.fresh?bookingContext(args.prefix):heldContext),
                // この偽装値は保存判断に使用されてはいけない。
                icsStatus:'ready',externalAcknowledged:true,events:[]};
            try {
                if(args.prefix==='booking') Reservations.register(options);
                else Reservations.reschedule(options);
                return {saved:true,message:''};
            }catch(e){return {saved:false,message:e.message};}
        }""",{'prefix':prefix,'fresh':fresh})

    for prefix in ['booking','reschedule']:
        for transition in ['clear','error','ready-busy','loading','uncheck','recheck','close','reopen','other-operation']:
            def stale_context(target, _, prefix=prefix, transition=transition):
                prepare_context(target,prefix)
                dialog='#reservation-dialog' if prefix=='booking' else '#reschedule-dialog'
                if transition=='clear': target.evaluate("document.getElementById('clear-files').click()")
                elif transition=='error':
                    target.evaluate("showSelectedFiles([new File(['bad'],'bad.ics')])")
                    target.evaluate('async()=>{await importQueue;}')
                elif transition=='ready-busy':
                    target.evaluate('source=>showSelectedFiles([new File([source],"busy.ics")])',event('new-conflict',start='20260629T110000',end='20260629T113000'))
                    target.evaluate('async()=>{await importQueue;}')
                elif transition=='loading':
                    target.evaluate("""()=>{
                        window.NativeReader=FileReader;
                        window.FileReader=class {readAsText(){window.mediumReader=this;}};
                        showSelectedFiles([new File(['pending'],'pending.ics')]);
                    }""")
                    target.wait_for_function('Boolean(window.mediumReader)')
                elif transition in ['uncheck','recheck']:
                    target.locator(f'#{prefix}-external-ack').uncheck()
                    if transition=='recheck': target.locator(f'#{prefix}-external-ack').check()
                elif transition=='close': target.locator(dialog).press('Escape')
                elif transition=='reopen':
                    target.locator(dialog).press('Escape')
                    if prefix=='booking': open_booking(target,4)
                    else: start_change(target)
                    target.locator(f'#{prefix}-external-ack').check()
                else:
                    target.locator(dialog).press('Escape')
                    if prefix=='booking':
                        start_change(target)
                        target.locator('#reschedule-external-ack').check()
                    else:
                        open_booking(target,4)
                        target.locator('#booking-external-ack').check()
                raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
                result=direct_save(target,prefix)
                assert not result['saved'],(prefix,transition,result)
                assert '再確認' in result['message'],result
                assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
                if transition=='ready-busy':
                    # 最新トークンでも古いevents:[]を渡して重複判定を回避できない。
                    fresh=direct_save(target,prefix,fresh=True)
                    assert not fresh['saved'] and 'ICS予定' in fresh['message'],fresh
                    assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
                if transition=='loading':
                    target.evaluate('async()=>{mediumReader.onerror();await importQueue;window.FileReader=NativeReader;}')
            run_booking_test(f'STEP6 Medium 古いcontext拒否・保存不変 {prefix}/{transition}',stale_context)

    for prefix in ['booking','reschedule']:
        for recovery in ['clear','error','loaded-safe']:
            def latest_context(target, _, prefix=prefix, recovery=recovery):
                prepare_context(target,prefix)
                before=read_bookings(target)
                if recovery=='clear':
                    target.evaluate("document.getElementById('clear-files').click()")
                    target.locator(f'#{prefix}-external-ack').check()
                else:
                    if recovery=='error':
                        target.evaluate("showSelectedFiles([new File(['bad'],'bad.ics')])")
                        target.evaluate('async()=>{await importQueue;}')
                    target.evaluate('source=>showSelectedFiles([new File([source],"normal.ics")])',empty_ics)
                    target.evaluate('async()=>{await importQueue;}')
                    assert target.locator(f'#{prefix}-external-warning').is_hidden()
                result=direct_save(target,prefix,fresh=True)
                assert result['saved'],result
                after=read_bookings(target)
                assert after[1]==before[1]  # キャンセル履歴維持。
                if prefix=='booking': assert len(after)==len(before)+1
                else:
                    assert len(after)==len(before)
                    assert after[0]=={**before[0],'start':1782698400000,'end':1782700200000}
                target.reload()
                assert read_bookings(target)==after
            run_booking_test(f'STEP6 Medium 最新contextの直接保存・復元 {prefix}/{recovery}',latest_context)

    for prefix in ['booking','reschedule']:
        def latest_events(target, _, prefix=prefix):
            prepare_context(target,prefix)
            # 未読み込みの古い同意トークンから、読み込み済みの最新トークンへ切替。
            target.evaluate('source=>showSelectedFiles([new File([source],"normal.ics")])',empty_ics)
            target.evaluate('async()=>{await importQueue;}')
            target.evaluate('prefix=>{window.heldContext=bookingContext(prefix);}',prefix)
            # トークン取得後に予定が更新されても、保存時は現在のMapを使用。
            target.evaluate("importedEvents.set('last-second',{start:1782698400000,end:1782700200000,status:'CONFIRMED',summary:'直前の予定'})")
            raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
            result=direct_save(target,prefix)
            assert not result['saved'] and 'ICS予定' in result['message'],result
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        run_booking_test(f'STEP6 Medium 現在のICS予定を直接呼び出しでも再取得 {prefix}',latest_events)

    def forged_context(target, _):
        prepare_context(target,'booking')
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        messages=target.evaluate("""()=>{
            const results=[];
            for(const options of [
                {icsStatus:'ready',externalAcknowledged:true,events:[]},
                {context:{...heldContext.context}},
                {context:{},icsStatus:'unloaded',externalAcknowledged:true}
            ]) {
                try{Reservations.register({...heldOptions,name:'偽装',email:'fake@example.com',...options});results.push('');}
                catch(e){results.push(e.message);}
            }
            try{Reservations.configureContext(()=>({icsStatus:'ready',events:[]}));results.push('');}
            catch(e){results.push(e.message);}
            return results;
        }""")
        assert all(messages),messages
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        # 同じトークンを別の予約枠へ転用しない。
        result=target.evaluate("""()=>{try{
            Reservations.register({...Calendar.slotRange(displayedMonday,6),name:'転用',email:'a@example.com',...heldContext});return '';
        }catch(e){return e.message;}}""")
        assert '再確認' in result
    run_booking_test('STEP6 Medium context偽装・別枠転用・取得元差し替えを拒否',forged_context)

    def consumed_context(target, _):
        prepare_context(target,'booking')
        result=direct_save(target,'booking')
        assert result['saved'],result
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        second=direct_save(target,'booking')
        assert not second['saved'] and '再確認' in second['message']
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
    run_booking_test('STEP6 Medium 成功した操作トークンを再利用しない',consumed_context)

    def final_storage_change(target, _):
        prepare_context(target,'booking')
        target.evaluate("""()=>{
            window.nativeUUID=crypto.randomUUID;
            crypto.randomUUID=()=>{
                const items=BookingStorage.read();
                BookingStorage.write([...items,{...items[0],id:'concurrent',...Calendar.slotRange(displayedMonday,6)}]);
                return 'new-review-id';
            };
        }""")
        result=direct_save(target,'booking')
        assert not result['saved'] and '保存直前' in result['message'],result
        assert [item['id'] for item in read_bookings(target)]==['step3-0','history','concurrent']
        target.evaluate('()=>{crypto.randomUUID=nativeUUID;}')
    run_booking_test('STEP6 Medium 保存直前の予約データ更新も上書きしない',final_storage_change)


    for prefix in ['booking','reschedule']:
        for transition in ['clear','new-busy']:
            def during_commit(target, _, prefix=prefix, transition=transition):
                prepare_context(target,prefix)
                if transition=='new-busy':
                    target.evaluate('source=>showSelectedFiles([new File([source],"ok.ics")])',empty_ics)
                    target.evaluate('async()=>{await importQueue;}')
                    target.evaluate('prefix=>{heldContext=bookingContext(prefix);}',prefix)
                raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
                target.evaluate("""transition=>{
                    window.nativeRead=BookingStorage.read;
                    let reads=0;
                    BookingStorage.read=()=>{
                        const data=nativeRead();
                        reads+=1;
                        if(reads===2) {
                            if(transition==='clear') document.getElementById('clear-files').click();
                            else importedEvents.set('at-commit',{start:1782698400000,end:1782700200000,status:'CONFIRMED'});
                        }
                        return data;
                    };
                }""",transition)
                result=direct_save(target,prefix)
                assert not result['saved'],result
                assert ('再確認' if transition=='clear' else 'ICS予定') in result['message']
                assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
                target.evaluate('()=>{BookingStorage.read=nativeRead;}')
            run_booking_test(f'STEP6 Medium 保存直前の{transition}を再検証 {prefix}',during_commit)


    # STEP 7: 実ダウンロードのバイト列をCSV標準ライブラリと独立したICSライブラリで検証。
    def export_open(target, format, scope='confirmed', names=False, individual=False):
        if format=='csv': target.locator('#csv-scope').select_option(scope)
        else: target.locator('#ics-include-names').set_checked(names)
        target.locator('#reservation-list .ics-export-button' if individual else '#csv-export' if format=='csv' else '#ics-export-all').first.click()
        assert target.locator('#export-dialog').evaluate('(e)=>e.open')

    def export_bytes(target):
        with target.expect_download() as pending:
            target.locator('#confirm-export').click()
        download=pending.value
        assert download.failure() is None
        data=Path(download.path()).read_bytes()
        target.locator('#export-dialog').wait_for(state='hidden')
        return data,download.suggested_filename

    def csv_rows(data):
        assert data.startswith(b'\xef\xbb\xbf')
        return list(csv.reader(io.StringIO(data.decode('utf-8-sig'),newline='')))

    def parsed_calendar(data):
        assert data.endswith(b'\r\n')
        assert b'\n' not in data.replace(b'\r\n',b'') and b'\r' not in data.replace(b'\r\n',b'')
        for line in data.split(b'\r\n'):
            assert len(line)<=75,(len(line),line)
            line.decode('utf-8','strict')
        calendar=ExternalCalendar.from_ical(data)
        assert str(calendar['VERSION'])=='2.0'
        assert calendar.get('PRODID')
        return [item for item in calendar.walk() if item.name=='VEVENT']

    for scope,count in [('confirmed',41),('cancelled',1),('all',42)]:
        def csv_scope(target, _, scope=scope,count=count):
            raw=seed(target)
            target.locator('#booking-search').fill('山田')
            export_open(target,'csv',scope=scope)
            assert f'対象 {count}件' in target.locator('#export-summary').inner_text()
            assert '氏名・メールアドレス' in target.locator('#export-privacy').inner_text()
            data,filename=export_bytes(target)
            rows=csv_rows(data)
            assert rows[0]==['予約ID','氏名','メールアドレス','予約日','開始時刻','終了時刻','状態','登録日時','キャンセル日時']
            assert len(rows)==count+1
            assert all(len(row)==9 for row in rows)
            expected=read_bookings(target)
            expected=[r for r in expected if scope=='all' or r['status']==scope]
            expected.sort(key=lambda r:(r['start'],r['createdAt']))
            assert [r[0] for r in rows[1:]]==[r['id'] for r in expected]
            assert len({r[0] for r in rows[1:]})==count
            assert filename==f'reservations-{scope}-2026-06-29.csv'
            assert 'ダウンロードを開始' in target.locator('#export-status').inner_text()
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
            assert target.locator('#booking-search').input_value()=='山田'
        run_booking_test(f'STEP7 CSV実ファイル・BOM・全対象・検索非依存 {scope}',csv_scope)

    def csv_special(target, _):
        seed(target,1)
        name='日本語, "引用"\n2行目;\\終わり'
        target.evaluate("""name=>{
            const items=BookingStorage.read();items[0].name=name;
            items[1].cancelledAt=Date.parse('2026-06-29T15:00:00Z');BookingStorage.write(items);reloadReservations();
        }""",name)
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        export_open(target,'csv',scope='all')
        data,_=export_bytes(target);rows=csv_rows(data)
        assert rows[1][1]==name
        assert rows[1][3:7]==['2026-06-29','09:00','09:30','確定']
        assert rows[1][7]=='1970-01-01 09:00:00' and rows[1][8]==''
        assert rows[2][3]=='2026-06-29' and rows[2][6]=='キャンセル済み'
        assert rows[2][8]=='2026-06-30 00:00:00'
        assert data.endswith(b'\r\n') and b'""' in data
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
    run_booking_test('STEP7 CSVのJST・元予約日・カンマ/引用符/改行のRFCエスケープ',csv_special)

    for payload in ['=1+1','+SUM(1,2)','-1+2','@SUM(1,2)','  =1+1','\t=1+1','\r=1+1','\n=1+1','\u200b=1+1']:
        def csv_formula(target, _, payload=payload):
            seed(target,1)
            target.evaluate("""id=>{const items=BookingStorage.read();items[0].id=id;items[0].name='=1+1';items[0].email='=test@example.com';BookingStorage.write(items);reloadReservations();}""",payload)
            raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
            export_open(target,'csv')
            data,_=export_bytes(target);row=csv_rows(data)[1]
            assert row[0]=="'"+payload
            assert row[1]=="'=1+1" and row[2]=="'=test@example.com"
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        run_booking_test(f'STEP7 CSVインジェクション対策 {payload!r}',csv_formula)

    for names in [False,True]:
        def ics_bulk(target, _, names=names):
            raw=seed(target,41)
            export_open(target,'ics',names=names)
            assert '対象 41件' in target.locator('#export-summary').inner_text()
            data,filename=export_bytes(target)
            events=parsed_calendar(data)
            expected=[r for r in read_bookings(target) if r['status']=='confirmed']
            assert len(events)==41
            assert len({str(e['UID']) for e in events})==41
            for e,r in zip(events,expected):
                assert e.decoded('DTSTART')==datetime.fromtimestamp(r['start']/1000,timezone.utc)
                assert e.decoded('DTEND')==datetime.fromtimestamp(r['end']/1000,timezone.utc)
                assert e.decoded('DTSTAMP')==datetime(2026,6,29,tzinfo=timezone.utc)
                assert str(e['STATUS'])=='CONFIRMED'
                assert str(e['SUMMARY'])==('予約: '+r['name'] if names else '予約あり')
                uid=hashlib.sha256(('reservation-ledger:v1:'+r['id']).encode()).hexdigest()+'@reservation-ledger.invalid'
                assert str(e['UID'])==uid
                assert r['email'].encode() not in data
            assert filename=='reservations-2026-06-29.ics'
            # アプリ側パーサーとも照合。ただし独立したicalendarが一次検証。
            parsed=target.evaluate('source=>ICSParser.parse(source)',data.decode())
            assert len(parsed)==41 and parsed[0]['start']==expected[0]['start']
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        run_booking_test(f'STEP7 ICS一括実ファイル・外部解析・UTC・プライバシー names={names}',ics_bulk)

    def individual_ics(target, _):
        seed(target,21)
        assert not target.locator('#ics-include-names').is_checked()
        target.locator('#booking-next').click()
        target.locator('#reservation-list .ics-export-button').click()
        assert '対象 1件' in target.locator('#export-summary').inner_text()
        data,filename=export_bytes(target);events=parsed_calendar(data)
        target_item=read_bookings(target)[20]
        assert len(events)==1
        assert events[0].decoded('DTSTART')==datetime.fromtimestamp(target_item['start']/1000,timezone.utc)
        assert str(events[0]['SUMMARY'])=='予約あり'
        assert target_item['name'].encode() not in data and target_item['email'].encode() not in data
        assert filename=='reservation-2026-06-29.ics'
        target.locator('#cancelled-tab').click()
        assert target.locator('#reservation-list .ics-export-button').count()==0
    run_booking_test('STEP7 2ページ目のICS個別出力・初期匿名設定・履歴ボタンなし',individual_ics)

    def ics_text(target, _):
        seed(target,1)
        name='日本語🙂,;\\\r\nBEGIN:VEVENT\n'+'長い名前'*15
        target.evaluate('name=>{const items=BookingStorage.read();items[0].name=name;BookingStorage.write(items);reloadReservations();}',name)
        export_open(target,'ics',names=True)
        data,_=export_bytes(target);events=parsed_calendar(data)
        assert len(events)==1
        assert str(events[0]['SUMMARY'])=='予約: '+name.replace('\r\n','\n')
        assert b'\r\n ' in data
        unfolded=re.sub(r'\r\n[ \t]','',data.decode())
        assert '\\,' in unfolded and '\\;' in unfolded and '\\\\' in unfolded and '\\n' in unfolded
        assert data.decode().count('BEGIN:VEVENT')==2  # 本物1件＋SUMMARY内のエスケープ済み文字列
        assert events[0].decoded('DTSTART').utcoffset()==timedelta(0)
    run_booking_test('STEP7 ICSの日本語/絵文字・TEXTエスケープ・CRLF・75オクテット折返し',ics_text)

    def stable_change_cancel(target, _):
        optional_book(target)
        export_open(target,'ics',individual=True)
        first,_=export_bytes(target);before=parsed_calendar(first)[0]
        export_open(target,'ics',individual=True)
        again,_=export_bytes(target)
        assert str(parsed_calendar(again)[0]['UID'])==str(before['UID'])
        start_change(target)
        target.locator('#reschedule-external-ack').check()
        target.locator('#confirm-reschedule').click()
        export_open(target,'ics',individual=True)
        changed,_=export_bytes(target);after=parsed_calendar(changed)[0]
        assert str(after['UID'])==str(before['UID'])
        assert after.decoded('DTSTART')-before.decoded('DTSTART')==timedelta(hours=1)
        target.locator('#reservation-list .cancel-reservation-button').click()
        target.locator('#confirm-cancel').click()
        export_open(target,'ics')
        assert '対象 0件' in target.locator('#export-summary').inner_text()
        assert target.locator('#confirm-export').is_disabled()
        assert '自動削除されません' in target.locator('#export-dialog').inner_text()
        target.locator('#dismiss-export').click()
        assert read_bookings(target)[0]['status']=='cancelled'
    run_booking_test('STEP7 同一予約の再出力/日時変更のUID安定・キャンセル後の除外',stable_change_cancel)

    def ics_private_id(target, _):
        seed(target,1)
        target.evaluate("""()=>{const items=BookingStorage.read();items[0].id='private@example.com';BookingStorage.write(items);reloadReservations();}""")
        export_open(target,'ics')
        data,_=export_bytes(target)
        assert b'private@example.com' not in data
        assert b'Hanako@Example.COM' not in data
        assert str(parsed_calendar(data)[0]['SUMMARY'])=='予約あり'
    run_booking_test('STEP7 ICS UIDにID内のメール等を平文で含めない',ics_private_id)

    for format in ['csv','ics']:
        def zero_export(target, _, format=format):
            raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
            export_open(target,format)
            assert target.locator('#confirm-export').is_disabled()
            assert '0件' in target.locator('#export-zero').inner_text()
            target.locator('#export-dialog').press('Escape')
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        run_booking_test(f'STEP7 {format}0件は案内してファイルを生成しない',zero_export)

    for format in ['csv','ics']:
        for failure in ['corrupt','version','denied']:
            def bad_export_data(target, _, format=format,failure=failure):
                seed(target,1)
                if failure=='denied': target.evaluate("() => {Storage.prototype.getItem=()=>{throw Error('denied');};}")
                else: target.evaluate('raw=>localStorage.setItem(BookingStorage.key,raw)','invalid' if failure=='corrupt' else '{"version":2,"reservations":[]}')
                target.locator('#csv-export' if format=='csv' else '#ics-export-all').click()
                assert '出力できません' in target.locator('#export-status').inner_text()
                assert not target.locator('#export-dialog').evaluate('(e)=>e.open')
                if failure!='denied':
                    assert target.evaluate('localStorage.getItem(BookingStorage.key)')==('invalid' if failure=='corrupt' else '{"version":2,"reservations":[]}')
            run_booking_test(f'STEP7 古い画面データで{format}出力しない {failure}',bad_export_data)

    for format in ['csv','ics']:
        def fresh_export(target, _, format=format):
            seed(target,1)
            export_open(target,format)
            target.evaluate("""()=>{
                const items=BookingStorage.read();items.push({...items[0],id:'new',name:'最新予約',...Calendar.slotRange(displayedMonday,4)});BookingStorage.write(items);
                window.createdURLs=0;window.nativeURL=URL.createObjectURL;URL.createObjectURL=(blob)=>{createdURLs++;return nativeURL(blob);};
            }""")
            raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
            target.locator('#confirm-export').click()
            target.wait_for_function('document.getElementById("export-error").textContent.includes("保存データが変わりました")')
            assert target.evaluate('createdURLs')==0
            assert '対象 2件' in target.locator('#export-summary').inner_text()
            data,_=export_bytes(target)
            assert len(csv_rows(data))-1==2 if format=='csv' else len(parsed_calendar(data))==2
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        run_booking_test(f'STEP7 {format}実行直前に最新データ再取得・件数変更なら再確認',fresh_export)

    def digest_race(target, _):
        seed(target,1)
        export_open(target,'ics')
        target.evaluate("""()=>{
            window.nativeDigest=crypto.subtle.digest.bind(crypto.subtle);
            crypto.subtle.digest=(...args)=>new Promise(resolve=>{window.completeDigest=async()=>resolve(await nativeDigest(...args));});
            window.createdURLs=0;window.nativeURL=URL.createObjectURL;URL.createObjectURL=blob=>{createdURLs++;return nativeURL(blob);};
        }""")
        target.locator('#confirm-export').click()
        target.wait_for_function('Boolean(window.completeDigest)')
        target.evaluate("""async()=>{
            const items=BookingStorage.read();Object.assign(items[0],Calendar.slotRange(displayedMonday,8));BookingStorage.write(items);
            crypto.subtle.digest=nativeDigest;await completeDigest();
        }""")
        target.wait_for_function('document.getElementById("export-error").textContent.includes("生成中")')
        assert target.evaluate('createdURLs')==0
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        data,_=export_bytes(target)
        assert parsed_calendar(data)[0].decoded('DTSTART')==datetime(2026,6,29,4,tzinfo=timezone.utc)
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
    run_booking_test('STEP7 ICS非同期生成中の予約変更で古い内容をダウンロードしない',digest_race)

    def download_error(target, _):
        seed(target,1)
        export_open(target,'csv')
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        target.evaluate("() => {window.nativeURL=URL.createObjectURL;URL.createObjectURL=()=>{throw Error('download failed');};}")
        target.locator('#confirm-export').click()
        target.wait_for_function('document.getElementById("export-error").textContent.includes("download failed")')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
        assert target.locator('#confirm-export').is_enabled()
        target.evaluate('()=>{URL.createObjectURL=nativeURL;}')
        data,_=export_bytes(target)
        assert len(csv_rows(data))==2
    run_booking_test('STEP7 ダウンロード生成失敗の案内・保存保護・再試行',download_error)

    def object_url_release(target, _):
        seed(target,1)
        target.evaluate("""()=>{
            window.nativeRevoke=URL.revokeObjectURL;window.revokedURLs=[];
            URL.revokeObjectURL=url=>{revokedURLs.push(url);nativeRevoke(url);};
        }""")
        export_open(target,'csv');export_bytes(target)
        assert target.evaluate('revokedURLs.length')==0
        target.clock.run_for(60000)
        assert target.evaluate('revokedURLs.length')==1
        export_open(target,'ics');export_bytes(target)
        target.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        assert target.evaluate('revokedURLs.length')==2
    run_booking_test('STEP7 Object URLをダウンロード猶予後・ページ離脱時に解放',object_url_release)

    def export_layout_keyboard(target, _):
        raw=seed(target,1)
        payload='<img src=x onerror=window.exportXSS=true>'+'A'*50
        target.evaluate('name=>{const items=BookingStorage.read();items[0].name=name;BookingStorage.write(items);reloadReservations();}',payload)
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        for width in [1440,390]:
            target.set_viewport_size({'width':width,'height':1000})
            target.locator('#csv-export').press('Enter')
            assert target.locator('#export-dialog').evaluate('(e)=>e.open')
            assert '対象 1件' in target.locator('#export-summary').inner_text()
            assert target.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert target.locator('#export-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            if os.environ.get('TEST_ARTIFACT_DIR'):
                target.screenshot(path=str(Path(os.environ['TEST_ARTIFACT_DIR'])/f'step7-export-{width}.png'))
            target.locator('#export-dialog').press('Escape')
            assert_focus(target,'#csv-export')
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
            target.locator('#ics-include-names').focus();target.locator('#ics-include-names').press('Space')
            export_open(target,'ics',names=True)
            data,_=export_bytes(target)
            assert str(parsed_calendar(data)[0]['SUMMARY'])=='予約: '+payload
            assert target.locator('#export-dialog img').count()==0
            assert target.evaluate('window.exportXSS===undefined')
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
    run_booking_test('STEP7 1440px/390px・キーボード/Esc/フォーカス・XSS・保存不変',export_layout_keyboard)

    for format in ['csv','ics']:
        def export_confirm_error(target, _, format=format):
            seed(target,1)
            export_open(target,format)
            target.evaluate("""() => {
                window.exportURLs=0;
                URL.createObjectURL=()=>{window.exportURLs++;throw new Error('unexpected download')};
                localStorage.setItem(BookingStorage.key,'corrupt after preview');
            }""")
            target.locator('#confirm-export').click()
            target.wait_for_function("document.getElementById('export-error').textContent.includes('出力できません')")
            assert target.evaluate('window.exportURLs')==0
            assert target.evaluate('localStorage.getItem(BookingStorage.key)')=='corrupt after preview'
        run_booking_test(f'STEP7 {format}確認後の保存データ異常でも出力停止',export_confirm_error)

    def export_cancelled_individual(target, _):
        seed(target,1)
        export_open(target,'ics',individual=True)
        target.evaluate("""() => {
            const items=BookingStorage.read();
            items[0].status='cancelled';items[0].cancelledAt=Date.now();
            BookingStorage.write(items);
            window.exportURLs=0;URL.createObjectURL=()=>{window.exportURLs++;throw new Error('unexpected download')};
        }""")
        raw=target.evaluate('localStorage.getItem(BookingStorage.key)')
        target.locator('#confirm-export').click()
        assert '0件' in target.locator('#export-zero').inner_text()
        assert target.locator('#confirm-export').is_disabled()
        assert target.evaluate('window.exportURLs')==0
        assert target.evaluate('localStorage.getItem(BookingStorage.key)')==raw
    run_booking_test('STEP7 個別ICS確認後のキャンセルは最新状態で出力除外',export_cancelled_individual)

    print(json.dumps({'sample_events': len(events), 'browser_errors': errors, 'passed': len(passed), 'failed': len(failures), 'test_groups': passed, 'failures': failures}, ensure_ascii=False))
    assert not failures, failures

    browser.close()

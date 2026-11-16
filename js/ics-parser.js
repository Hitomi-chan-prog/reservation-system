"use strict";
window.ICSParser = (() => {
  const fail = (message) => { throw new Error(message); };
  function text(value) {
    let result = '';
    for (let i = 0; i < value.length; i += 1) {
      if (value[i] !== '\\') {
        result += value[i];
        continue;
      }
      i += 1;
      if (i === value.length) fail('末尾の文字列エスケープが不完全です。');
      const escaped = value[i];
      if (escaped === 'n' || escaped === 'N') result += '\n';
      else if (['\\', ',', ';'].includes(escaped)) result += escaped;
      else fail('未対応の文字列エスケープです。');
    }
    return result;
  }
  function property(line) {
    const match = /^([A-Za-z0-9-]+)((?:;[A-Za-z0-9-]+=(?:"[^"]*"|[^":;\r\n]+))*):(.*)$/.exec(line);
    if (!match) fail('不正または未対応のICS構文です。');
    const params = {};
    for (const item of match[2].matchAll(/;([A-Za-z0-9-]+)=("[^"]*"|[^":;\r\n]+)/g)) {
      const key = item[1].toUpperCase();
      if (key in params) fail('パラメーターが重複しています。');
      const rawValue = item[2];
      params[key] = rawValue.startsWith('"') && rawValue.endsWith('"')
        ? rawValue.slice(1, -1) : rawValue;
    }
    return { name: match[1].toUpperCase(), params, value: match[3] };
  }
  function date(prop) {
    const { value, params } = prop;
    if (Object.keys(params).some((key) => !['TZID', 'VALUE'].includes(key))) fail('未対応の日時パラメーターです。');
    const hasTZID = Object.prototype.hasOwnProperty.call(params, 'TZID');
    const hasValue = Object.prototype.hasOwnProperty.call(params, 'VALUE');
    if (hasTZID && params.TZID !== 'Asia/Tokyo') fail(`未対応のタイムゾーンです：${params.TZID}`);
    const allDay = params.VALUE === 'DATE';
    if (hasValue && !['DATE', 'DATE-TIME'].includes(params.VALUE)) fail('未対応の日時形式です。');
    const m = (allDay ? /^(\d{4})(\d{2})(\d{2})$/ : /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?$/).exec(value);
    if (!m || (hasTZID && (allDay || m[7]))) fail('日時の書式が不正です。');
    const [y, mo, d, h, mi, s] = [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4] || 0), Number(m[5] || 0), Number(m[6] || 0)];
    const check = new Date(0);
    check.setUTCFullYear(y, mo - 1, d);
    check.setUTCHours(h, mi, s, 0);
    if (check.getUTCFullYear() !== y || check.getUTCMonth() !== mo - 1 || check.getUTCDate() !== d || h > 23 || mi > 59 || s > 59) fail('存在しない日時です。');
    return { timestamp: check.getTime() - (m[7] ? 0 : 540 * 60000), allDay };
  }
  function parse(source) {
    const lines = source.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\n[ \t]/g, '').split('\n').filter((line) => line !== '');
    if (lines[0] !== 'BEGIN:VCALENDAR' || lines[lines.length - 1] !== 'END:VCALENDAR') fail('VCALENDAR形式のICSファイルではありません。');
    const events = [];
    let current = null;
    let version = false;
    for (const line of lines.slice(1, -1)) {
      const p = property(line);
      if (p.name === 'BEGIN') {
        if (p.value !== 'VEVENT' || current) fail('未対応のICSコンポーネントです（繰り返し・VTIMEZONE・アラーム等は未対応）。');
        current = {};
      } else if (p.name === 'END') {
        if (p.value !== 'VEVENT' || !current) fail('VEVENTの構造が不正です。');
        if (!current.UID || !current.DTSTART) fail('UIDまたはDTSTARTがありません。');
        const start = date(current.DTSTART);
        const end = current.DTEND ? date(current.DTEND) : start.allDay ? { timestamp: start.timestamp + 86400000, allDay: true } : fail('DTENDがありません。');
        if (start.allDay !== end.allDay || end.timestamp <= start.timestamp) fail('予定の終了日時が不正です。');
        const status = current.STATUS ? current.STATUS.value.toUpperCase() : 'CONFIRMED';
        if (!['CONFIRMED', 'TENTATIVE', 'CANCELLED'].includes(status)) fail('未対応のSTATUSです。');
        events.push({ uid: text(current.UID.value), start: start.timestamp, end: end.timestamp, summary: current.SUMMARY ? text(current.SUMMARY.value) : '予定あり', status, allDay: start.allDay });
        current = null;
      } else if (current) {
        if (['RRULE', 'RDATE', 'EXDATE', 'EXRULE', 'RECURRENCE-ID', 'DURATION', 'TRANSP'].includes(p.name)) fail(`未対応のICS機能です：${p.name}`);
        const supported = ['UID', 'DTSTART', 'DTEND', 'SUMMARY', 'STATUS'];
        const ignored = ['DTSTAMP', 'CREATED', 'LAST-MODIFIED', 'SEQUENCE', 'DESCRIPTION', 'LOCATION', 'URL', 'CLASS', 'CATEGORIES', 'ORGANIZER', 'ATTENDEE'];
        if (!supported.includes(p.name) && !ignored.includes(p.name) && !p.name.startsWith('X-')) fail(`未対応の予定プロパティです：${p.name}`);
        if (supported.includes(p.name)) {
          if (current[p.name]) fail('予定プロパティが重複しています。');
          if (!['DTSTART', 'DTEND'].includes(p.name) && Object.keys(p.params).length) fail('未対応の文字列パラメーターです。');
          if (p.name === 'UID' && !p.value.trim()) fail('UIDが空です。');
          current[p.name] = p;
        }
      } else {
        if (p.name === 'VERSION') { if (version || p.value !== '2.0') fail('VERSIONは2.0のみ対応しています。'); version = true; }
        else if (p.name === 'CALSCALE' && p.value !== 'GREGORIAN') fail('未対応の暦です：CALSCALEはGREGORIANのみ対応しています。');
        else if (p.name === 'METHOD' && p.value !== 'PUBLISH') fail('METHODはPUBLISHのみ対応しています。');
        else if (p.name === 'X-WR-TIMEZONE' && p.value !== 'Asia/Tokyo') fail('未対応のカレンダータイムゾーンです。');
        else if (!['PRODID', 'CALSCALE', 'METHOD', 'X-WR-TIMEZONE'].includes(p.name) && !p.name.startsWith('X-')) fail(`未対応のカレンダープロパティです：${p.name}`);
      }
    }
    if (current || !version) fail('ICSの構造またはVERSIONが不正です。');
    return events;
  }
  return { parse };
})();

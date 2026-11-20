"use strict";
// 保存・DOM操作をしない出力形式の生成。入力配列は変更しない。
window.ReservationExport = (() => {
  const headers = ['予約ID', '氏名', 'メールアドレス', '予約日', '開始時刻', '終了時刻', '状態', '登録日時', 'キャンセル日時'];
  const jst = timestamp => new Date(timestamp + 9 * 3600000).toISOString().slice(0, 19).replace('T', ' ');
  const dateKey = timestamp => jst(timestamp).slice(0, 10);
  function select(items, { format, scope = 'confirmed', id = null }) {
    if (!['csv', 'ics'].includes(format) || !['confirmed', 'cancelled', 'all'].includes(scope)) throw new Error('出力条件が不正です。');
    return items.filter(item => (format === 'ics' ? item.status === 'confirmed' : scope === 'all' || item.status === scope) &&
      (id === null || item.id === id)).sort((a, b) => a.start - b.start || a.createdAt - b.createdAt);
  }
  function csvCell(value) {
    let text = String(value);
    // 引用だけでは数式を防げない。先頭空白・制御/書式文字の後の数式記号も中和する。
    if (/^[\s\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u206f]*[=+\-@]/u.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
    return `"${text.replace(/"/g, '""')}"`;
  }
  function csv(items) {
    const rows = [headers, ...items.map(item => [item.id, item.name, item.email, dateKey(item.start),
      jst(item.start).slice(11, 16), jst(item.end).slice(11, 16), item.status === 'confirmed' ? '確定' : 'キャンセル済み',
      jst(item.createdAt), item.cancelledAt === null ? '' : jst(item.cancelledAt)])];
    return '\ufeff' + rows.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
  }
  function utc(timestamp) {
    const date = new Date(timestamp);
    if (!Number.isFinite(date.getTime()) || date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) throw new Error('ICS出力に対応できない日時です。');
    return date.toISOString().slice(0, 19).replace(/[-:]/g, '') + 'Z';
  }
  function text(value) {
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value)) throw new Error('ICSの予定名に出力できない制御文字があります。');
    return value.replace(/\\/g, '\\\\').replace(/\r\n|\r|\n/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;');
  }
  function fold(line) {
    const encoder = new TextEncoder();
    const lines = [];
    let part = '', octets = 0;
    for (const char of line) {
      const size = encoder.encode(char).length;
      if (octets + size > 75) { lines.push(part); part = ' '; octets = 1; }
      part += char;
      octets += size;
    }
    lines.push(part);
    return lines.join('\r\n');
  }
  async function uid(id) {
    if (!window.crypto || !window.crypto.subtle) throw new Error('この環境では安全なUIDを生成できません。Web Crypto対応ブラウザで開いてください。');
    const hash = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode('reservation-ledger:v1:' + id));
    return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('') + '@reservation-ledger.invalid';
  }
  async function ics(items, { includeNames = false, timestamp = Date.now() } = {}) {
    const stamp = utc(timestamp);
    const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Reservation Ledger//Booking Export//JA', 'CALSCALE:GREGORIAN'];
    for (const item of items) {
      if (item.status !== 'confirmed') continue;
      lines.push('BEGIN:VEVENT', 'UID:' + await uid(item.id), 'DTSTAMP:' + stamp,
        'DTSTART:' + utc(item.start), 'DTEND:' + utc(item.end), 'SUMMARY:' + text(includeNames ? `予約: ${item.name}` : '予約あり'),
        'STATUS:CONFIRMED', 'END:VEVENT');
    }
    lines.push('END:VCALENDAR');
    return lines.map(fold).join('\r\n') + '\r\n';
  }
  return { select, csv, ics, dateKey };
})();

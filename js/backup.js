"use strict";
// バックアップ専用の外側の形式。予約の妥当性は既存の保存形式検証に委ねる。
window.ReservationBackup = (() => {
  const format = 'reservation-ledger.backup';
  // 通常の数十件より十分大きい学習用の上限。読み込みと出力で同じUTF-8バイト数を使う。
  const maxBytes = 5 * 1024 * 1024;
  const sizeLabel = `${maxBytes / (1024 * 1024)}MiB（${maxBytes.toLocaleString('ja-JP')}バイト）`;
  function checkSize(bytes) {
    if (!Number.isSafeInteger(bytes) || bytes < 0) throw new Error('JSONファイルのサイズを確認できません。復元を中止しました。');
    if (bytes > maxBytes) throw new Error(`JSONは最大${sizeLabel}です。上限を超えるため処理を中止しました。データの一部だけを処理することはありません。`);
  }
  function checkSourceSize(source) {
    if (typeof source !== 'string') throw new Error('JSON文字列を確認できません。');
    // UTF-8はUTF-16コード単位数以上になる。巨大な文字列はエンコード前にも拒否する。
    checkSize(source.length);
    checkSize(new TextEncoder().encode(source).byteLength);
  }
  const keys = (value, expected) => value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...expected].sort().join(',');
  const reservationKeys = ['id', 'name', 'email', 'start', 'end', 'status', 'createdAt', 'cancelledAt'];
  function validate(value) {
    if (!keys(value, ['format', 'backupVersion', 'exportedAt', 'reservationCount', 'data']) ||
        value.format !== format || value.backupVersion !== 1 ||
        typeof value.exportedAt !== 'string' || !Number.isFinite(Date.parse(value.exportedAt)) ||
        new Date(value.exportedAt).toISOString() !== value.exportedAt ||
        !Number.isSafeInteger(value.reservationCount) || value.reservationCount < 0 ||
        !keys(value.data, ['version', 'reservations']) || !Array.isArray(value.data.reservations) ||
        value.reservationCount !== value.data.reservations.length ||
        !value.data.reservations.every(item => keys(item, reservationKeys))) {
      throw new Error('対応するJSONバックアップ形式・バージョン・日時・件数ではありません。');
    }
    // 現在時刻による拒否は行わない。過去の予約も履歴として全件保持する。
    return Reservations.validateData(value.data);
  }
  function create(reservations, now = Date.now()) {
    const data = { version: 1, reservations: Reservations.validateData({ version: 1, reservations }) };
    return { format, backupVersion: 1, exportedAt: new Date(now).toISOString(), reservationCount: data.reservations.length, data };
  }
  function serialize(reservations, now = Date.now()) {
    const source = JSON.stringify(create(reservations, now), null, 2);
    checkSourceSize(source);
    return source;
  }
  function parse(source) {
    checkSourceSize(source);
    let value;
    try { value = JSON.parse(source.replace(/^\ufeff/, '')); }
    catch { throw new Error('JSONとして読み込めません。バックアップファイルを確認してください。'); }
    return validate(value);
  }
  return { create, parse, serialize, checkSize, maxBytes, sizeLabel };
})();

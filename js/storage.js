"use strict";
window.BookingStorage = (() => {
  const key = 'reservation-ledger.bookings.v1';
  function read() {
    let raw;
    try { raw = window.localStorage.getItem(key); }
    catch { throw new Error('予約データにアクセスできません。ブラウザの保存設定を確認してください。'); }
    if (raw === null) return [];
    try { return Reservations.validateData(JSON.parse(raw)); }
    catch { throw new Error('保存された予約データが不正です。既存データを保護するため登録・キャンセルを停止しています。保存データを確認してください。'); }
  }
  function write(reservations) {
    const data = { version: 1, reservations };
    Reservations.validateData(data);
    try { window.localStorage.setItem(key, JSON.stringify(data)); }
    catch { throw new Error('予約データを保存できませんでした。保存容量やブラウザの設定を確認してください。操作は完了していません。'); }
  }
  return { key, read, write };
})();

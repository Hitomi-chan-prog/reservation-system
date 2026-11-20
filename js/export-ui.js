"use strict";
// エクスポートは最新の保存データだけを読み、確認後にブラウザ内で生成する。
window.ExportUI = (() => {
  const byId = id => document.getElementById(id);
  const urls = new Map();
  let plan = null;
  let busy = false;
  let opener = null;
  const scopeLabels = { confirmed: '確定予約のみ', cancelled: 'キャンセル履歴のみ', all: 'すべての予約' };
  function read(options) { return ReservationExport.select(BookingStorage.read(), options); }
  function preview(items) {
    plan.fingerprint = JSON.stringify(items);
    byId('export-summary').textContent = `${plan.format.toUpperCase()} / ${plan.id !== null ? '個別の確定予約' : plan.format === 'ics' ? '確定予約のみ' : scopeLabels[plan.scope]} / 対象 ${items.length}件`;
    byId('export-privacy').textContent = plan.format === 'csv' ?
      'CSVには予約ID・氏名・メールアドレス・日時が含まれます。共有先と保管場所にご注意ください。確認・集計用であり、完全なバックアップ復元用ではありません。' :
      `${plan.includeNames ? '氏名を予定名に含めます。' : '予定名は「予約あり」です。氏名は含めません。'} メールアドレスは出力しません。`;
    byId('export-zero').textContent = items.length ? '' : '出力対象は0件です。ファイルは作成しません。対象の選択・保存済み予約を確認してください。';
    byId('confirm-export').disabled = items.length === 0;
  }
  function message(value) { byId('export-status').textContent = value; }
  function open(format, id = null, source = null) {
    if (busy || byId('export-dialog').open) return;
    try {
      const options = { format, id, scope: byId('csv-scope').value, includeNames: byId('ics-include-names').checked };
      const items = read(options);
      plan = options;
      opener = source || document.activeElement;
      preview(items);
      byId('export-error').textContent = '';
      message('');
      byId('export-dialog').showModal();
    } catch (error) { message('出力できません：' + error.message); }
  }
  function release(url) {
    if (!urls.has(url)) return;
    clearTimeout(urls.get(url));
    urls.delete(url);
    URL.revokeObjectURL(url);
  }
  function download(content, type, filename) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    // ブラウザがBlobを取得する猶予を置く。ページ離脱時にも解放する。
    urls.set(url, setTimeout(() => release(url), 60000));
    try { anchor.click(); }
    catch (error) { release(url); throw error; }
    finally { anchor.remove(); }
  }
  function close() {
    byId('export-dialog').close();
    plan = null;
    if (opener && opener.isConnected && opener.getClientRects().length) opener.focus();
    else byId('reservations-heading').focus();
  }
  byId('csv-export').addEventListener('click', event => open('csv', null, event.currentTarget));
  byId('ics-export-all').addEventListener('click', event => open('ics', null, event.currentTarget));
  byId('dismiss-export').addEventListener('click', () => { if (!busy) close(); });
  byId('export-dialog').addEventListener('cancel', event => { event.preventDefault(); if (!busy) close(); });
  byId('confirm-export').addEventListener('click', async () => {
    if (!plan || busy) return;
    busy = true;
    byId('confirm-export').disabled = true;
    byId('dismiss-export').disabled = true;
    byId('export-error').textContent = '';
    try {
      const items = read(plan);
      if (JSON.stringify(items) !== plan.fingerprint || !items.length) {
        preview(items);
        byId('export-error').textContent = '保存データが変わりました。更新した対象件数と設定を確認して、再度ダウンロードしてください。';
        return;
      }
      const now = Date.now();
      const content = plan.format === 'csv' ? ReservationExport.csv(items) : await ReservationExport.ics(items, { includeNames: plan.includeNames, timestamp: now });
      // Web Cryptoの非同期生成中に変更された場合も、古いスナップショットを出力しない。
      const latest = read(plan);
      if (JSON.stringify(latest) !== plan.fingerprint) {
        preview(latest);
        byId('export-error').textContent = '生成中に保存データが変わりました。再確認してから出力してください。';
        return;
      }
      const filename = `${plan.id === null ? 'reservations' : 'reservation'}-${plan.format === 'csv' ? plan.scope + '-' : ''}${ReservationExport.dateKey(now)}.${plan.format}`;
      download(content, plan.format === 'csv' ? 'text/csv;charset=utf-8' : 'text/calendar;charset=utf-8', filename);
      message(`${items.length}件の${plan.format.toUpperCase()}のダウンロードを開始しました。端末でファイルを確認してください。`);
      close();
    } catch (error) {
      byId('export-error').textContent = '出力できません：' + error.message;
      message('出力できません：' + error.message);
    } finally {
      busy = false;
      byId('dismiss-export').disabled = false;
      if (plan) byId('confirm-export').disabled = false;
      if (plan && byId('export-zero').textContent) byId('confirm-export').disabled = true;
    }
  });
  window.addEventListener('pagehide', () => { for (const url of [...urls.keys()]) release(url); });
  return { open };
})();

"use strict";
(() => {
  const el = id => document.getElementById(id);
  const urls = new Map();
  document.querySelectorAll('[data-backup-size-note]').forEach(note => { note.textContent = `JSONの出力・復元の上限は${ReservationBackup.sizeLabel}です。上限超過時は読み込み・ダウンロードせず、保存データを変更しません。`; });
  let savePlan = null, restorePlan = null, opener = null, reader = null, generation = 0;
  const status = message => { el('backup-status').textContent = message; };
  function release(url) {
    if (!urls.has(url)) return;
    clearTimeout(urls.get(url)); urls.delete(url); URL.revokeObjectURL(url);
  }
  function download(content, now) {
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = `reservation-backup-${ReservationExport.dateKey(now)}.json`;
    document.body.append(link);
    urls.set(url, setTimeout(() => release(url), 60000));
    try { link.click(); } catch (error) { release(url); throw error; } finally { link.remove(); }
  }
  function focusBack() {
    const fallback = el(el('admin-view').hidden ? 'reservations-heading' : 'admin-heading');
    (opener && opener.isConnected && opener.getClientRects().length ? opener : fallback).focus();
  }
  function invalidateRead() {
    generation += 1;
    if (reader && reader.readyState === 1) reader.abort();
    reader = null; restorePlan = null;
    el('restore-replace-ack').checked = false;
    el('confirm-restore').disabled = true;
  }
  function closeRestore() {
    invalidateRead(); el('restore-file').value = ''; el('restore-dialog').close(); focusBack();
  }
  function updateSave(snapshot) {
    savePlan = snapshot;
    el('backup-count').textContent = `保存済みの全予約 ${snapshot.reservations.length}件（確定予約・キャンセル履歴）をバックアップします。`;
  }
  el('save-backup').addEventListener('click', event => {
    try {
      updateSave(BookingStorage.snapshot()); opener = event.currentTarget;
      el('backup-error').textContent = ''; status(''); el('backup-dialog').showModal();
    } catch (error) { status('バックアップできません：' + error.message); }
  });
  function closeSave() { savePlan = null; el('backup-dialog').close(); focusBack(); }
  el('dismiss-backup').addEventListener('click', closeSave);
  el('backup-dialog').addEventListener('cancel', event => { event.preventDefault(); closeSave(); });
  el('confirm-backup').addEventListener('click', () => {
    if (!savePlan || !el('backup-dialog').open) return;
    try {
      const current = BookingStorage.snapshot();
      if (current.raw !== savePlan.raw) {
        updateSave(current);
        el('backup-error').textContent = '保存データが変わりました。更新した件数を確認して、もう一度保存してください。';
        return;
      }
      const now = Date.now();
      download(ReservationBackup.serialize(current.reservations, now), now);
      status(`${current.reservations.length}件のJSONバックアップのダウンロードを開始しました。端末のファイルを確認してください。`);
      closeSave();
    } catch (error) { el('backup-error').textContent = 'バックアップできません：' + error.message; }
  });
  el('open-restore').addEventListener('click', event => {
    try {
      const current = BookingStorage.snapshot(); invalidateRead();
      opener = event.currentTarget; status(''); el('restore-file').value = '';
      el('restore-current').textContent = `現在保存されている予約：${current.reservations.length}件`;
      el('restore-count').textContent = 'JSONバックアップを選択してください。選択だけでは保存しません。';
      el('restore-error').textContent = ''; el('restore-replace-warning').hidden = true;
      el('restore-dialog').showModal();
    } catch (error) { status('復元を開始できません：' + error.message); }
  });
  el('restore-file').addEventListener('change', () => {
    invalidateRead(); const ownGeneration = generation;
    el('restore-error').textContent = ''; el('restore-replace-warning').hidden = true;
    const file = el('restore-file').files[0];
    el('restore-count').textContent = file ? `${file.name} を検証しています…` : 'JSONバックアップを選択してください。';
    if (!file) return;
    let bytes;
    try { bytes = file.size; } catch { /* 取得不能も共通の日本語エラーにする。 */ }
    try { ReservationBackup.checkSize(bytes); }
    catch (error) {
      el('restore-file').value = ''; el('restore-count').textContent = '読み込みは開始していません。';
      el('restore-error').textContent = error.message; return;
    }
    const currentReader = new FileReader(); reader = currentReader;
    const active = () => generation === ownGeneration && reader === currentReader && el('restore-dialog').open;
    currentReader.onload = () => {
      if (!active()) return;
      reader = null;
      try {
        ReservationBackup.checkSize(currentReader.result && currentReader.result.byteLength);
        let source;
        try { source = new TextDecoder('utf-8', { fatal: true }).decode(currentReader.result); }
        catch { throw new Error('UTF-8のJSONファイルとして読み込めません。バックアップを確認してください。'); }
        const reservations = ReservationBackup.parse(source);
        const current = BookingStorage.snapshot();
        restorePlan = { reservations, raw: current.raw, replacing: current.reservations.length > 0 };
        el('restore-current').textContent = `現在保存されている予約：${current.reservations.length}件`;
        el('restore-count').textContent = `検証済みバックアップ：${reservations.length}件（確定 ${reservations.filter(item => item.status === 'confirmed').length}件・キャンセル ${reservations.filter(item => item.status === 'cancelled').length}件）`;
        el('restore-replace-warning').hidden = !restorePlan.replacing;
        el('confirm-restore').disabled = restorePlan.replacing;
      } catch (error) {
        restorePlan = null; el('restore-file').value = ''; el('restore-count').textContent = '検証に失敗しました。復元は行っていません。';
        el('restore-error').textContent = error.message;
      }
    };
    currentReader.onerror = () => { if (active()) { reader = null; el('restore-file').value = ''; el('restore-count').textContent = '読み込みに失敗しました。'; el('restore-error').textContent = 'バックアップファイルを読み込めません。再選択してください。'; } };
    try { currentReader.readAsArrayBuffer(file); }
    catch { if (active()) { reader = null; el('restore-file').value = ''; el('restore-error').textContent = 'バックアップファイルを読み込めません。'; } }
  });
  el('restore-replace-ack').addEventListener('change', () => {
    el('confirm-restore').disabled = !restorePlan || (restorePlan.replacing && !el('restore-replace-ack').checked);
  });
  el('confirm-restore').addEventListener('click', () => {
    if (!restorePlan || !el('restore-dialog').open) return;
    try {
      if (restorePlan.replacing && !el('restore-replace-ack').checked) throw new Error('現在の予約をすべて置き換える専用の確認チェックが必要です。');
      const current = BookingStorage.snapshot();
      if (current.raw !== restorePlan.raw) {
        invalidateRead(); el('restore-file').value = '';
        throw new Error('確認後に保存データが変わりました。復元を中止しました。ファイルを選び直して確認してください。');
      }
      const count = restorePlan.reservations.length;
      BookingStorage.write(restorePlan.reservations);
      closeRestore();
      window.dispatchEvent(new Event('reservation-data-restored'));
      status(`${count}件の予約をバックアップから復元しました。予約一覧・カレンダー・履歴を確認してください。`);
    } catch (error) { el('restore-error').textContent = error.message; }
  });
  el('dismiss-restore').addEventListener('click', closeRestore);
  el('restore-dialog').addEventListener('cancel', event => {
    // ファイル選択の中止がバブリングしても、復元確認そのものは閉じない。
    if (event.target !== event.currentTarget) return;
    event.preventDefault(); closeRestore();
  });
  window.addEventListener('storage', event => {
    if ((event.key === BookingStorage.key || event.key === null) && el('restore-dialog').open && restorePlan) {
      invalidateRead(); el('restore-file').value = ''; el('restore-error').textContent = '別タブで保存データが更新されました。復元を中止しました。ファイルを選び直して確認してください。';
    }
  });
  window.addEventListener('pagehide', () => { invalidateRead(); for (const url of [...urls.keys()]) release(url); });
})();

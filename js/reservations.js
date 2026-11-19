"use strict";
window.Reservations = (() => {
  const fail = (message) => { throw new Error(message); };
  const isTime = (value) => Number.isSafeInteger(value) && Number.isFinite(new Date(value).getTime());
  function input(name, email) {
    if (typeof name !== 'string' || typeof email !== 'string') fail('氏名とメールアドレスを入力してください。');
    name = name.trim();
    email = email.trim();
    if (Array.from(name).length < 1 || Array.from(name).length > 100) fail('氏名は前後の空白を除いて1〜100文字で入力してください。');
    const emailInput = document.createElement('input');
    emailInput.type = 'email';
    emailInput.value = email;
    if (!email || email.length > 254 || /[\r\n]/.test(email) || !emailInput.validity.valid) fail('メールアドレスは254文字以内の正しい形式で入力してください。');
    return { name, email };
  }
  function validRange(start, end) {
    if (!isTime(start) || !isTime(end) || end - start !== 1800000) return false;
    const local = new Date(start + 540 * 60000);
    return local.getUTCDay() >= 1 && local.getUTCDay() <= 5 &&
      local.getUTCHours() >= 9 && local.getUTCHours() < 18 &&
      [0, 30].includes(local.getUTCMinutes()) && local.getUTCSeconds() === 0 && local.getUTCMilliseconds() === 0;
  }
  function validateData(data) {
    if (!data || data.version !== 1 || !Array.isArray(data.reservations)) fail('保存データの形式またはバージョンが不正です。');
    const ids = new Set();
    const occupied = new Set();
    return data.reservations.map((item) => {
      if (!item || typeof item.id !== 'string' || !item.id.trim() || item.id.length > 100 || ids.has(item.id) ||
          !validRange(item.start, item.end) || !['confirmed', 'cancelled'].includes(item.status) ||
          !isTime(item.createdAt) || item.createdAt > item.start ||
          (item.status === 'confirmed' ? item.cancelledAt !== null : !isTime(item.cancelledAt) || item.cancelledAt < item.createdAt)) fail('保存された予約データが不正です。');
      const normalized = input(item.name, item.email);
      if (normalized.name !== item.name || normalized.email !== item.email) fail('保存された入力値が不正です。');
      if (item.status === 'confirmed' && occupied.has(item.start)) fail('保存データに重複した予約があります。');
      ids.add(item.id);
      if (item.status === 'confirmed') occupied.add(item.start);
      return { id: item.id, ...normalized, start: item.start, end: item.end, status: item.status, createdAt: item.createdAt, cancelledAt: item.cancelledAt };
    });
  }
  function uniqueId(existing) {
    // file://等でrandomUUIDがなくても暗号学的乱数を使用。安全な乱数がなければ保存しない。
    for (let attempt = 0; attempt < 5; attempt += 1) {
      let id;
      if (window.crypto && typeof window.crypto.randomUUID === 'function') id = window.crypto.randomUUID();
      else if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
        id = Array.from(window.crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('');
      } else fail('安全な予約IDを生成できないため登録できません。');
      if (!existing.some((item) => item.id === id)) return id;
    }
    fail('予約IDを生成できませんでした。もう一度お試しください。');
  }
  // 画面起動時に一度だけ接続する。呼び出し元の状態・同意・予定は保存判断に使わない。
  let contextProvider = null;
  function configureContext(provider) {
    if (contextProvider || typeof provider !== 'function') fail('予約確認の取得元は変更できません。');
    contextProvider = provider;
  }
  function resolveContext(context, request) {
    if (!contextProvider) fail('予約確認を初期化できていません。画面を開き直してください。');
    return contextProvider(context, request);
  }
  function commit(next, current, context, request) {
    const latest = BookingStorage.read();
    if (JSON.stringify(latest) !== JSON.stringify(current)) fail('保存直前に予約データが更新されました。内容を再確認してください。');
    const policy = resolveContext(context, request);
    checkDestination({ ...request, ...policy }, latest.filter(item => item.id !== request.excludeId));
    BookingStorage.write(next);
    policy.consume();
    return next;
  }
  function checkICS(icsStatus, externalAcknowledged) {
    if (icsStatus === 'ready') return;
    if (icsStatus === 'loading') fail('ICS読み込み中です。完了するまで確定できません。');
    if (icsStatus === 'error') fail('ICS読み込みエラーが未解決です。再読み込みまたはクリアしてください。');
    if (icsStatus !== 'unloaded') fail('ICS状態が不正です。画面を確認してください。');
    if (externalAcknowledged !== true) fail('ICS未読み込みです。外部予定が未確認であることへの確認チェックが必要です。');
  }
  function checkDestination({ start, end, icsStatus, externalAcknowledged, events }, current) {
    checkICS(icsStatus, externalAcknowledged);
    if (!validRange(start, end)) fail('予約は月〜金9:00〜18:00の30分枠を選択してください。');
    if (start <= Date.now()) fail('過去または開始済みの日時は予約できません。');
    if ((icsStatus === 'ready' && events.some(event => event.status !== 'CANCELLED' && Calendar.overlaps(event, { start, end }))) ||
        current.some(item => item.status === 'confirmed' && Calendar.overlaps(item, { start, end }))) {
      fail('この枠にはICS予定または予約があるため登録できません。');
    }
  }
  const unchanged = (item, snapshot) => Boolean(item && snapshot &&
    ['id', 'name', 'email', 'start', 'end', 'status', 'createdAt', 'cancelledAt'].every(key => item[key] === snapshot[key]));
  function reschedule({ snapshot, start, end, context }) {
    const current = BookingStorage.read();
    const target = current.find(item => snapshot && item.id === snapshot.id);
    if (!target || target.status !== 'confirmed') fail('この予約は存在しないか、キャンセル済みのため変更できません。');
    if (!unchanged(target, snapshot)) fail('別タブなどで予約が変更されています。日時変更を中止して一覧からやり直してください。');
    if (target.start === start && target.end === end) fail('同じ日時への変更は不要です。別の枠を選択してください。');
    const request = { operation: 'reschedule', start, end, snapshot, excludeId: target.id };
    checkDestination({ start, end, ...resolveContext(context, request) }, current.filter(item => item.id !== target.id));
    const next = current.map(item => item.id === target.id ? { ...item, start, end } : item);
    return commit(next, current, context, request);
  }
  function register({ name, email, start, end, context }) {
    const normalized = input(name, email);
    const request = { operation: 'booking', start, end };
    const policy = resolveContext(context, request);
    checkICS(policy.icsStatus, policy.externalAcknowledged);
    if (!validRange(start, end)) fail('予約は月〜金9:00〜18:00の30分枠を選択してください。');
    if (start <= Date.now()) fail('過去または開始済みの日時は予約できません。');
    const current = BookingStorage.read();
    checkDestination({ start, end, ...policy }, current);
    const now = Date.now();
    if (start <= now) fail('開始済みの日時は予約できません。別の枠を選択してください。');
    const reservation = { id: uniqueId(current), ...normalized, start, end, status: 'confirmed', createdAt: now, cancelledAt: null };
    const next = [...current, reservation];
    return commit(next, current, context, request);
  }
  function cancel(id) {
    const current = BookingStorage.read();
    const target = current.find((item) => item.id === id);
    if (!target || target.status !== 'confirmed') fail('この予約は存在しないか、すでにキャンセル済みです。');
    const next = current.map((item) => item.id === id ? { ...item, status: 'cancelled', cancelledAt: Date.now() } : item);
    BookingStorage.write(next);
    return next;
  }
  return { input, validRange, validateData, register, cancel, reschedule, unchanged, configureContext };
})();

"use strict";

const byId = (id) => document.getElementById(id);
const today = Calendar.today();
const startOfWeek = Calendar.startOfWeek;
let displayedMonday = startOfWeek(today);
let importedEvents = new Map();
let importedFiles = new Map();
let importGeneration = 0;
let importQueue = Promise.resolve();
const activeReads = new Set();
const dateAt = (day) => new Date(displayedMonday.getTime() + day * 86400000);
const shortDate = (date) => `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
const timeAt = (slot) => `${String(9 + Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
const weekdays = ["月", "火", "水", "木", "金"];
let reservations = [];
let selectedRange = null;
let cancelId = null;
let pendingImports = 0;
let importFailed = false;
let importErrors = [];
let rescheduleSnapshot = null;
let rescheduleRange = null;
const tokyoDate = (timestamp) => new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' }).format(timestamp);
const tokyoTime = (timestamp) => new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(timestamp);
const bookingLabel = (item) => `${tokyoDate(item.start)} ${tokyoTime(item.start)}–${tokyoTime(item.end)}`;
let icsRevision = 0;
let lastConfirmationState = '';
const icsStatus = () => pendingImports > 0 ? 'loading' : importFailed ? 'error' : importedFiles.size ? 'ready' : 'unloaded';
// トークンの記録と操作世代はこのクロージャだけが保持する。ICSの取得元は上の状態管理。
const bookingContext = (() => {
  const issued = new WeakMap();
  const sessions = { booking: null, reschedule: null };
  const dialogFor = prefix => byId(prefix === 'booking' ? 'reservation-dialog' : 'reschedule-dialog');
  const rangeFor = prefix => prefix === 'booking' ? selectedRange : rescheduleRange;
  const retry = () => { throw new Error('ICS状態または同意・予約操作が変わりました。確認画面で内容を再確認してください。'); };
  function issue(prefix) {
    const session = sessions[prefix];
    const range = rangeFor(prefix);
    if (!session || !dialogFor(prefix).open || !range) retry();
    const token = Object.freeze({});
    issued.set(token, { prefix, session, agreement: session.agreement, revision: icsRevision,
      generation: importGeneration, state: icsStatus(), start: range.start, end: range.end });
    return Object.freeze({ context: token });
  }
  issue.begin = prefix => { sessions[prefix] = { agreement: 0 }; };
  issue.end = prefix => { sessions[prefix] = null; };
  issue.agreementChanged = prefix => {
    if (sessions[prefix]) sessions[prefix].agreement += 1;
  };
  Reservations.configureContext((token, request) => {
    const record = token && issued.get(token);
    const prefix = request.operation;
    const session = sessions[prefix];
    const range = rangeFor(prefix);
    if (!record || record.prefix !== prefix || !session || record.session !== session ||
        record.agreement !== session.agreement || !dialogFor(prefix).open || !range ||
        record.revision !== icsRevision || record.generation !== importGeneration || record.state !== icsStatus() ||
        record.start !== range.start || record.end !== range.end || request.start !== range.start || request.end !== range.end) retry();
    if (prefix === 'reschedule' && !Reservations.unchanged(request.snapshot, rescheduleSnapshot)) retry();
    return { icsStatus: icsStatus(), events: [...importedEvents.values()],
      externalAcknowledged: byId(`${prefix}-external-ack`).checked,
      consume() {
        issued.delete(token);
        if (sessions[prefix] === session) sessions[prefix] = null;
      }
    };
  });
  return Object.freeze(issue);
})();

function createTextElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function openReservationDialog(date, slot) {
  if (rescheduleSnapshot) {
    byId('reschedule-external-ack').checked = false;
    bookingContext.begin('reschedule');
    rescheduleRange = Calendar.slotRange(date, slot);
    byId('reschedule-before').textContent = `${bookingLabel(rescheduleSnapshot)} / ${rescheduleSnapshot.name} / ${rescheduleSnapshot.email}`;
    byId('reschedule-after').textContent = bookingLabel(rescheduleRange);
    byId('reschedule-error').textContent = '';
    updateBookingHint();
    byId('reschedule-dialog').showModal();
    return;
  }
  selectedRange = Calendar.slotRange(date, slot);
  byId("reservation-dialog").querySelector("form").reset();
  bookingContext.begin('booking');
  byId("booking-error").textContent = "";
  updateBookingHint();
  byId("selected-slot").textContent = `${date.getUTCFullYear()}年${date.getUTCMonth() + 1}月${date.getUTCDate()}日（${weekdays[(date.getUTCDay() + 6) % 7]}） ${timeAt(slot)}–${timeAt(slot + 1)}`;
  byId("reservation-dialog").showModal();
}

function renderCalendar() {
  byId("today").textContent = Calendar.today().toLocaleDateString("ja-JP", { timeZone: "UTC", year: "numeric", month: "long", day: "numeric", weekday: "short" });
  const monday = dateAt(0);
  const friday = dateAt(4);
  byId("week-label").textContent = `${shortDate(monday)} ～ ${shortDate(friday)} (${monday.getUTCFullYear()}${monday.getUTCFullYear() !== friday.getUTCFullYear() ? `–${friday.getUTCFullYear()}` : ""})`;
  const heading = document.createElement("tr");
  const corner = createTextElement("th", "時刻");
  corner.scope = "col";
  heading.append(corner);
  weekdays.forEach((weekday, day) => {
    const cell = createTextElement("th", weekday);
    cell.scope = "col";
    cell.append(createTextElement("small", shortDate(dateAt(day))));
    heading.append(cell);
  });
  byId("calendar-head").replaceChildren(heading);
  const rows = document.createDocumentFragment();
  for (let slot = 0; slot < 18; slot += 1) {
    const row = document.createElement("tr");
    const label = createTextElement("th", timeAt(slot));
    label.scope = "row";
    row.append(label);
    weekdays.forEach((weekday, day) => {
      const date = dateAt(day);
      const result = Calendar.availability(date, slot, [...importedEvents.values()], reservations.filter(item => !rescheduleSnapshot || item.id !== rescheduleSnapshot.id));
      const reservation = result.reservation;
      const cell = document.createElement("td");
      if (reservation) {
        cell.className = "reserved";
        cell.textContent = reservation.name;
        cell.title = reservation.name;
        cell.setAttribute("aria-label", `${shortDate(date)} ${timeAt(slot)} 予約済み ${reservation.name}`);
      } else if (result.state === "busy") {
        cell.className = "busy";
        cell.textContent = "予定あり";
        cell.title = result.busy.map((event) => event.summary).join("、");
        cell.setAttribute("aria-label", `${shortDate(date)} ${timeAt(slot)} ICS予定あり ${cell.title}`);
      } else {
        const button = createTextElement("button", "");
        button.type = "button";
        if (rescheduleSnapshot) {
          const range = Calendar.slotRange(date, slot);
          button.disabled = range.start <= Date.now();
          if (range.start === rescheduleSnapshot.start) button.textContent = '現在の予約';
        }
        button.setAttribute("aria-label", `${shortDate(date)}（${weekday}）${timeAt(slot)}–${timeAt(slot + 1)} 空き・${rescheduleSnapshot ? "変更先を選択" : "予約入力を開く"}`);
        button.addEventListener("click", () => openReservationDialog(date, slot));
        cell.append(button);
      }
      row.append(cell);
    });
    rows.append(row);
  }
  byId("calendar-body").replaceChildren(rows);
}

const listStates = {
  booking: {status: 'confirmed', query: '', date: '', page: 1},
  admin: {status: 'all', query: '', date: '', page: 1}
};
function renderReservations() {
  const confirmed = reservations.filter(item => item.status === 'confirmed').length;
  const cancelled = reservations.filter(item => item.status === 'cancelled').length;
  byId('confirmed-tab').textContent = `確定予約（${confirmed}件）`;
  byId('cancelled-tab').textContent = `キャンセル履歴（${cancelled}件）`;
  byId('reservation-count').textContent = `${reservations.length}件`;
  byId('admin-reservation-count').textContent = `全${reservations.length}件（確定 ${confirmed}件・キャンセル ${cancelled}件）`;
  for (const [prefix, containerId, withActions] of [['booking', 'reservation-list', true], ['admin', 'admin-reservation-list', false]]) {
    const result = ReservationList.select(reservations, listStates[prefix]);
    listStates[prefix].page = result.page;
    const cards = document.createDocumentFragment();
    result.items.forEach((reservation) => {
      const card = createTextElement("article", "", "reservation-card");
      const top = createTextElement("div", "", "card-top");
      const detail = createTextElement("div", "", "reservation-detail");
      detail.append(createTextElement("strong", bookingLabel(reservation)), createTextElement("p", `${reservation.name} 様`, "name"), createTextElement("p", reservation.email, "email"));
      top.append(createTextElement("span", reservation.status === 'confirmed' ? "確定" : "取消", "stamp"), detail);
      card.append(top, createTextElement('p', reservation.status === 'confirmed' ? '確定' : 'キャンセル済み', 'description'));
      if (reservation.status === 'confirmed' && [...importedEvents.values()].some((event) => event.status !== 'CANCELLED' && Calendar.overlaps(event, reservation))) {
        card.append(createTextElement('p', 'ICS予定と競合しています。予約は保持されています。', 'conflict-warning'));
      }
      if (withActions && reservation.status === 'confirmed') {
        const actions = createTextElement("div", "", "card-actions");
        const cancel = createTextElement("button", "キャンセル", "button");
        cancel.type = "button";
        cancel.addEventListener('click', () => {
          cancelId = reservation.id;
          byId('cancel-detail').textContent = `${bookingLabel(reservation)} / ${reservation.name} / ${reservation.email}`;
          byId('cancel-error').textContent = '';
          byId('cancel-dialog').showModal();
        });
        const change = createTextElement('button', '日時変更', 'button reschedule-button');
        change.type = 'button';
        change.dataset.reservationId = reservation.id;
        change.addEventListener('click', () => startReschedule(reservation.id));
        actions.append(change, cancel);
        card.append(actions);
      }
      if (reservation.status === 'cancelled') {
        card.append(createTextElement('p', `キャンセル日時：${tokyoDate(reservation.cancelledAt)} ${tokyoTime(reservation.cancelledAt)}（日本時間）`, 'description'));
      }
      cards.append(card);
    });
    if (!result.total) {
      const state = listStates[prefix];
      const message = state.query.trim() || state.date ? '検索条件に一致する予約はありません' :
        state.status === 'cancelled' ? 'キャンセル履歴はまだありません' : '予約はまだありません';
      cards.append(createTextElement('p', message, 'description'));
    }
    byId(containerId).replaceChildren(cards);
    byId(`${prefix}-range`).textContent = `全${result.total}件中 ${result.first}〜${result.last}件を表示`;
    byId(`${prefix}-page`).textContent = `${result.page} / ${result.pages}ページ`;
    byId(`${prefix}-previous`).disabled = result.page === 1;
    byId(`${prefix}-next`).disabled = result.page === result.pages;
  }
}
for (const prefix of ['booking', 'admin']) {
  for (const [field, property] of [['search', 'query'], ['date', 'date'], ...(prefix === 'admin' ? [['status', 'status']] : [])]) {
    byId(`${prefix}-${field}`).addEventListener('input', event => {
      listStates[prefix][property] = event.target.value;
      listStates[prefix].page = 1;
      renderReservations();
    });
  }
  byId(`${prefix}-clear-date`).addEventListener('click', () => {
    byId(`${prefix}-date`).value = '';
    listStates[prefix].date = '';
    listStates[prefix].page = 1;
    renderReservations();
  });
  for (const [direction, delta] of [['previous', -1], ['next', 1]]) {
    byId(`${prefix}-${direction}`).addEventListener('click', () => {
      listStates[prefix].page += delta;
      renderReservations();
    });
  }
}
for (const status of ['confirmed', 'cancelled']) {
  const tab = byId(`${status}-tab`);
  tab.addEventListener('click', () => {
    listStates.booking.status = status;
    listStates.booking.page = 1;
    for (const value of ['confirmed', 'cancelled']) {
      byId(`${value}-tab`).setAttribute('aria-selected', String(value === status));
      byId(`${value}-tab`).tabIndex = value === status ? 0 : -1;
    }
    byId('reservation-panel').setAttribute('aria-labelledby', tab.id);
    renderReservations();
  });
  tab.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'confirmed' : event.key === 'End' ? 'cancelled' : status === 'confirmed' ? 'cancelled' : 'confirmed';
    byId(`${next}-tab`).click();
    byId(`${next}-tab`).focus();
  });
}
function icsMessage() {
  if (pendingImports > 0) return '読み込み中：予定を確認しています。完了するまで確定できません。';
  if (importFailed) return 'エラー：予定を確認できませんでした。ICSファイルを再読み込みまたは明示的にクリアしてください。確定できません。';
  if (!importedFiles.size) return '未読み込み：ICSファイルは未読み込みです。保存済み予約のみを確認しています。外部カレンダーの予定とは重複する可能性があります。';
  return '読み込み成功：ICSファイルを読み込みました。保存済み予約と読み込んだICS予定を確認しています。予定の最新性は保証されません。';
}
function rescheduleProblem() {
  if (!rescheduleSnapshot) return '';
  const current = reservations.find(item => item.id === rescheduleSnapshot.id);
  if (!current || current.status !== 'confirmed' || !Reservations.unchanged(current, rescheduleSnapshot)) {
    return '別タブなどで予約が変更・キャンセルされています。日時変更を中止して一覧からやり直してください。';
  }
  if (rescheduleRange && rescheduleRange.start === rescheduleSnapshot.start) return '同じ日時への変更は不要です。別の枠を選択してください。';
  return '';
}
function updateBookingHint() {
  const state = icsStatus();
  const confirmationState = `${icsRevision}:${state}`;
  if (lastConfirmationState !== confirmationState) {
    byId('booking-external-ack').checked = false;
    byId('reschedule-external-ack').checked = false;
    lastConfirmationState = confirmationState;
  }
  const message = icsMessage();
  byId('ics-state').textContent = message;
  byId('ics-state').className = state === 'error' ? 'error-message' : state === 'unloaded' ? 'external-warning' : 'description';
  const problem = rescheduleProblem();
  for (const prefix of ['booking', 'reschedule']) {
    const needsAck = state === 'unloaded';
    const acknowledged = byId(`${prefix}-external-ack`).checked;
    byId(`${prefix}-external-warning`).hidden = !needsAck;
    const confirmationHint = needsAck ? acknowledged ? '外部予定が未確認であることを確認しました。日時と入力内容を確認して確定してください。' : '確定するには、外部予定が未確認であることへの確認チェックが必要です。' : '';
    byId(`${prefix}-hint`).textContent = [message, confirmationHint, prefix === 'reschedule' ? problem : ''].filter(Boolean).join(' ');
    byId(`confirm-${prefix}`).disabled = !(['ready', 'unloaded'].includes(state)) || (needsAck && !acknowledged) ||
      (prefix === 'reschedule' && (!rescheduleRange || Boolean(problem)));
  }
  byId('reschedule-mode-error').textContent = problem;
}
for (const prefix of ['booking', 'reschedule']) {
  byId(`${prefix}-external-ack`).addEventListener('change', () => {
    bookingContext.agreementChanged(prefix);
    updateBookingHint();
  });
}
function startReschedule(id) {
  try {
    const current = BookingStorage.read();
    const target = current.find(item => item.id === id && item.status === 'confirmed');
    if (!target) throw new Error('変更できる確定予約がありません。');
    reservations = current;
    rescheduleSnapshot = { ...target };
    rescheduleRange = null;
    const local = new Date(target.start + 9 * 3600000);
    displayedMonday = startOfWeek(new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate())));
    byId('reschedule-current').textContent = `${bookingLabel(target)} / ${target.name} / ${target.email}`;
    byId('reschedule-mode').hidden = false;
    showStorageError('');
    renderAll();
    byId('reschedule-mode').scrollIntoView({ block: 'center' });
    byId('stop-reschedule').focus();
  } catch (error) { showStorageError(error.message); }
}
function stopReschedule() {
  bookingContext.end('reschedule');
  const id = rescheduleSnapshot && rescheduleSnapshot.id;
  rescheduleSnapshot = null;
  rescheduleRange = null;
  byId('reschedule-mode').hidden = true;
  renderAll();
  const button = [...document.querySelectorAll('#reservation-list .reschedule-button')]
    .find(element => element.dataset.reservationId === id && element.getClientRects().length);
  const fallback = byId(byId('booking-view').hidden ? 'admin-heading' : 'reservations-heading');
  (button || fallback).focus();
}
byId('stop-reschedule').addEventListener('click', stopReschedule);
function dismissReschedule() {
  byId('reschedule-dialog').close();
  stopReschedule();
}
byId('dismiss-reschedule').addEventListener('click', dismissReschedule);
byId('reschedule-dialog').addEventListener('cancel', event => {
  event.preventDefault();
  dismissReschedule();
});
byId('confirm-reschedule').addEventListener('click', () => {
  byId('operation-status').textContent = '';
  try {
    reservations = Reservations.reschedule({ snapshot: rescheduleSnapshot, ...rescheduleRange,
      ...bookingContext('reschedule') });
    byId('reschedule-dialog').close();
    showStorageError('');
    stopReschedule();
    byId('operation-status').textContent = '予約日時を変更し、保存しました。';
  } catch (error) {
    byId('reschedule-error').textContent = error.message;
    reloadReservations();
  }
});
function renderAll() {
  renderCalendar();
  renderReservations();
  updateBookingHint();
  const conflicts = reservations.filter((item) => item.status === 'confirmed' && [...importedEvents.values()].some((event) => event.status !== 'CANCELLED' && Calendar.overlaps(event, item)));
  byId('conflict-warning').textContent = conflicts.length ? `ICS予定と競合する予約が${conflicts.length}件あります：${conflicts.map(bookingLabel).join('、')}。予約は自動削除していません。` : '';
}
function showStorageError(message) {
  byId('storage-error').textContent = message;
  byId('admin-storage-error').textContent = message;
}
function reloadReservations() {
  try {
    reservations = BookingStorage.read();
    showStorageError('');
  } catch (error) {
    showStorageError(error.message);
  }
  renderAll();
}

function importSummary() {
  return importedFiles.size
    ? `読み込み済み：${[...importedFiles].map(([name, count]) => `${name}（${count}件）`).join("、")} · UID重複除去後 ${importedEvents.size}件（キャンセル ${[...importedEvents.values()].filter((e) => e.status === "CANCELLED").length}件）`
    : "未読み込み · ICSは任意です。外部予定は未確認のため、確定時に確認チェックが必要です。";
}
function readICSFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      activeReads.delete(task);
      if (error) reject(error);
      else resolve(value);
    };
    const task = { cancel() {
      try { if (typeof reader.abort === 'function') reader.abort(); }
      catch { /* 中止通知が失敗しても世代を破棄し、待機は解除する。 */ }
      finally { finish(new Error('読み込みを中止しました。')); }
    } };
    activeReads.add(task);
    reader.onload = () => { if (!settled) finish(null, reader.result); };
    reader.onerror = reader.onabort = () => finish(new Error('ファイルを読み込めませんでした。'));
    try { reader.readAsText(file, 'UTF-8'); }
    catch (error) { finish(error); }
  });
}
function showSelectedFiles(files) {
  const selected = Array.from(files);
  const generation = importGeneration;
  if (!selected.length) return;
  icsRevision += 1;
  if (pendingImports === 0) {
    importFailed = false;
    importErrors = [];
    byId('import-error').textContent = '';
  }
  pendingImports += 1;
  updateBookingHint();
  importQueue = importQueue.then(async () => {
    if (generation !== importGeneration) return;
    const errors = [];
    for (const file of selected) {
      if (generation !== importGeneration) return;
      try {
        if (!/\.ics$/i.test(file.name)) throw new Error(".ics ファイルを選択してください。");
        const source = await readICSFile(file);
        if (generation !== importGeneration) return;
        const events = ICSParser.parse(source);
        if (generation !== importGeneration) return;
        events.forEach((event) => importedEvents.set(event.uid, event));
        importedFiles.set(file.name, events.length);
      } catch (error) {
        errors.push(`${file.name}：${error.message}`);
      }
    }
    if (generation !== importGeneration) return;
    importErrors.push(...errors);
    if (importErrors.length) importFailed = true;
    byId("import-status").textContent = importSummary();
    byId("import-error").textContent = importErrors.length ? `読み込みエラー（失敗したファイルは取り込んでいません）：${importErrors.join(" / ")}` : "";
    renderAll();
  }).finally(() => {
    if (generation === importGeneration) {
      pendingImports -= 1;
      updateBookingHint();
    }
  });
}

function dismissBooking() {
  byId('reservation-dialog').close();
  bookingContext.end('booking');
}
document.querySelector('.close-button').addEventListener('click', dismissBooking);
byId('reservation-dialog').addEventListener('cancel', () => bookingContext.end('booking'));
for (const prefix of ['booking', 'reschedule']) {
  const dialog = byId(prefix === 'booking' ? 'reservation-dialog' : 'reschedule-dialog');
  dialog.addEventListener('close', () => { if (!dialog.open) bookingContext.end(prefix); });
}
byId("previous-week").addEventListener("click", () => { displayedMonday.setUTCDate(displayedMonday.getUTCDate() - 7); renderCalendar(); });
byId("next-week").addEventListener("click", () => { displayedMonday.setUTCDate(displayedMonday.getUTCDate() + 7); renderCalendar(); });
byId("current-week").addEventListener("click", () => { displayedMonday = startOfWeek(Calendar.today()); renderCalendar(); });
byId("choose-file").addEventListener("click", () => byId("ics-file").click());
byId("ics-file").addEventListener("change", (event) => { showSelectedFiles(event.target.files); event.target.value = ""; });
byId("clear-files").addEventListener("click", () => {
  importGeneration += 1;
  icsRevision += 1;
  importQueue = Promise.resolve();
  for (const task of [...activeReads]) task.cancel();
  pendingImports = 0;
  importFailed = false;
  importErrors = [];
  importedEvents.clear();
  importedFiles.clear();
  byId("ics-file").value = "";
  byId("import-status").textContent = importSummary();
  byId("import-error").textContent = "";
  renderAll();
});
const dropZone = byId("drop-zone");
["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.add("drag-over"); }));
["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.remove("drag-over"); }));
dropZone.addEventListener("drop", (event) => showSelectedFiles(event.dataTransfer.files));
// エリア外にドロップしてもブラウザがファイルへ移動しないようにします。
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());
function renderRoute() {
  const isAdmin = location.hash === "#admin";
  byId("booking-view").hidden = isAdmin;
  byId("admin-view").hidden = !isAdmin;
}
window.addEventListener("hashchange", renderRoute);
byId('booking-form').addEventListener('submit', (event) => {
  event.preventDefault();
  byId('operation-status').textContent = '';
  try {
    if (!selectedRange) throw new Error('予約枠を選択してください。');
    reservations = Reservations.register({
      ...selectedRange, name: byId('customer-name').value, email: byId('customer-email').value,
      ...bookingContext('booking')
    });
    byId('reservation-dialog').close();
    showStorageError('');
    byId('operation-status').textContent = '予約を登録しました。このブラウザに保存されています。';
    renderAll();
  } catch (error) {
    byId('booking-error').textContent = error.message;
    reloadReservations();
  }
});
byId('confirm-cancel').addEventListener('click', () => {
  byId('operation-status').textContent = '';
  try {
    reservations = Reservations.cancel(cancelId);
    byId('cancel-dialog').close();
    showStorageError('');
    byId('operation-status').textContent = '予約をキャンセルし、保存しました。';
    renderAll();
  } catch (error) {
    byId('cancel-error').textContent = error.message;
    reloadReservations();
  }
});
byId('dismiss-booking').addEventListener('click', dismissBooking);
byId('dismiss-cancel').addEventListener('click', () => byId('cancel-dialog').close());
window.addEventListener('storage', (event) => {
  if (event.key === BookingStorage.key || event.key === null) {
    byId('operation-status').textContent = '';
    reloadReservations();
  }
});
reloadReservations();
renderRoute();

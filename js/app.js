"use strict";

const byId = (id) => document.getElementById(id);
const today = Calendar.today();
const startOfWeek = Calendar.startOfWeek;
let displayedMonday = startOfWeek(today);
let importedEvents = new Map();
let importedFiles = new Map();
let importGeneration = 0;
let importQueue = Promise.resolve();
const dateAt = (day) => new Date(displayedMonday.getTime() + day * 86400000);
const shortDate = (date) => `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
const timeAt = (slot) => `${String(9 + Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
const weekdays = ["月", "火", "水", "木", "金"];
let reservations = [];
let selectedRange = null;
let cancelId = null;
let pendingImports = 0;
const tokyoDate = (timestamp) => new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' }).format(timestamp);
const tokyoTime = (timestamp) => new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(timestamp);
const bookingLabel = (item) => `${tokyoDate(item.start)} ${tokyoTime(item.start)}–${tokyoTime(item.end)}`;
const icsReady = () => importedFiles.size > 0 && pendingImports === 0;

function createTextElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function openReservationDialog(date, slot) {
  selectedRange = Calendar.slotRange(date, slot);
  byId("reservation-dialog").querySelector("form").reset();
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
      const result = Calendar.availability(date, slot, [...importedEvents.values()], reservations);
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
        button.setAttribute("aria-label", `${shortDate(date)}（${weekday}）${timeAt(slot)}–${timeAt(slot + 1)} 空き・予約入力を開く`);
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
        actions.append(cancel);
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
function updateBookingHint() {
  byId('confirm-booking').disabled = !icsReady();
  byId('booking-hint').textContent = icsReady() ? '選択日時と入力内容を確認して予約を確定してください。' : 'ICSファイルを読み込み、完了するまで予約を確定できません。';
}
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
    : "未読み込み · ICSを読み込むまで新規予約は確定できません。";
}
function showSelectedFiles(files) {
  const selected = Array.from(files);
  const generation = importGeneration;
  if (!selected.length) return;
  pendingImports += 1;
  updateBookingHint();
  importQueue = importQueue.then(async () => {
    if (generation !== importGeneration) return;
    const errors = [];
    for (const file of selected) {
      try {
        if (!/\.ics$/i.test(file.name)) throw new Error(".ics ファイルを選択してください。");
        const source = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reader.onabort = () => reject(new Error("ファイルを読み込めませんでした。"));
          reader.readAsText(file, "UTF-8");
        });
        const events = ICSParser.parse(source);
        if (generation !== importGeneration) return;
        events.forEach((event) => importedEvents.set(event.uid, event));
        importedFiles.set(file.name, events.length);
      } catch (error) {
        errors.push(`${file.name}：${error.message}`);
      }
    }
    if (generation !== importGeneration) return;
    byId("import-status").textContent = importSummary();
    byId("import-error").textContent = errors.length ? `読み込みエラー（失敗したファイルは取り込んでいません）：${errors.join(" / ")}` : "";
    renderAll();
  }).finally(() => {
    pendingImports -= 1;
    updateBookingHint();
  });
}

document.querySelector(".close-button").addEventListener("click", () => {
  byId("reservation-dialog").close();
});
byId("previous-week").addEventListener("click", () => { displayedMonday.setUTCDate(displayedMonday.getUTCDate() - 7); renderCalendar(); });
byId("next-week").addEventListener("click", () => { displayedMonday.setUTCDate(displayedMonday.getUTCDate() + 7); renderCalendar(); });
byId("current-week").addEventListener("click", () => { displayedMonday = startOfWeek(Calendar.today()); renderCalendar(); });
byId("choose-file").addEventListener("click", () => byId("ics-file").click());
byId("ics-file").addEventListener("change", (event) => { showSelectedFiles(event.target.files); event.target.value = ""; });
byId("clear-files").addEventListener("click", () => {
  importGeneration += 1;
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
      icsReady: icsReady(), events: [...importedEvents.values()]
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
byId('dismiss-booking').addEventListener('click', () => byId('reservation-dialog').close());
byId('dismiss-cancel').addEventListener('click', () => byId('cancel-dialog').close());
window.addEventListener('storage', (event) => {
  if (event.key === BookingStorage.key || event.key === null) {
    byId('operation-status').textContent = '';
    reloadReservations();
  }
});
reloadReservations();
renderRoute();

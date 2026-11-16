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
const demoMonday = startOfWeek(today);
const demoReservations = [
  { day: 0, slot: 0, name: "田中 花子", email: "hanako@example.com" },
  { day: 2, slot: 5, name: "山田 太郎", email: "taro@example.com" }
].map((reservation) => {
  const date = new Date(demoMonday.getTime() + reservation.day * 86400000);
  return { ...reservation, date, ...Calendar.slotRange(date, reservation.slot) };
});

function createTextElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function openReservationDialog(date, slot) {
  byId("reservation-dialog").querySelector("form").reset();
  byId("selected-slot").textContent = `${date.getUTCFullYear()}年${date.getUTCMonth() + 1}月${date.getUTCDate()}日（${weekdays[(date.getUTCDay() + 6) % 7]}） ${timeAt(slot)}–${timeAt(slot + 1)}`;
  byId("reservation-dialog").showModal();
}

function renderCalendar() {
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
      const result = Calendar.availability(date, slot, [...importedEvents.values()], demoReservations);
      const reservation = result.reservation;
      const cell = document.createElement("td");
      if (reservation) {
        cell.className = "reserved";
        cell.textContent = `${reservation.name}（デモ）`;
        cell.setAttribute("aria-label", `${shortDate(date)} ${timeAt(slot)} 予約済み ${reservation.name}（仮データ）`);
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

function renderReservations() {
  const cards = document.createDocumentFragment();
  demoReservations.forEach((reservation) => {
    const card = createTextElement("article", "", "reservation-card");
    const top = createTextElement("div", "", "card-top");
    const detail = document.createElement("div");
    detail.append(createTextElement("strong", `${shortDate(reservation.date)}（${weekdays[reservation.day]}） ${timeAt(reservation.slot)}–${timeAt(reservation.slot + 1)}`), createTextElement("p", `${reservation.name} 様`, "name"), createTextElement("p", reservation.email, "email"));
    top.append(createTextElement("span", "デモ", "stamp"), detail);
    const actions = createTextElement("div", "", "card-actions");
    const cancel = createTextElement("button", "キャンセル", "button");
    cancel.type = "button";
    cancel.disabled = true;
    cancel.title = "STEP 3以降に実装予定";
    actions.append(cancel);
    card.append(top, actions);
    cards.append(card);
  });
  byId("reservation-list").replaceChildren(cards);
  byId("reservation-count").textContent = `${demoReservations.length}件`;
}

function importSummary() {
  return importedFiles.size
    ? `読み込み済み：${[...importedFiles].map(([name, count]) => `${name}（${count}件）`).join("、")} · UID重複除去後 ${importedEvents.size}件（キャンセル ${[...importedEvents.values()].filter((e) => e.status === "CANCELLED").length}件）`
    : "未読み込み · ICS予定は未確認です。予約2件は学習用デモです。";
}
function showSelectedFiles(files) {
  const selected = Array.from(files);
  const generation = importGeneration;
  if (!selected.length) return;
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
    renderCalendar();
  });
}

document.querySelector(".close-button").addEventListener("click", () => {
  byId("reservation-dialog").close();
});
byId("today").textContent = today.toLocaleDateString("ja-JP", { timeZone: "UTC", year: "numeric", month: "long", day: "numeric", weekday: "short" });
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
  renderCalendar();
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
renderCalendar();
renderReservations();
renderRoute();

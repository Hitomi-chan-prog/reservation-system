"use strict";

// STEP 1: 固定の見本データ。ICSや入力内容から予定・予約を作成しません。
const byId = (id) => document.getElementById(id);
const today = new Date();
const startOfWeek = (date) => {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
  return monday;
};
let displayedMonday = startOfWeek(today);
const dateAt = (day) => {
  const date = new Date(displayedMonday);
  date.setDate(date.getDate() + day);
  return date;
};
const shortDate = (date) => `${date.getMonth() + 1}/${date.getDate()}`;
const timeAt = (slot) => `${String(9 + Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
const weekdays = ["月", "火", "水", "木", "金"];
const demoMonday = startOfWeek(today);
const demoReservations = [
  { day: 0, slot: 0, name: "田中 花子", email: "hanako@example.com" },
  { day: 2, slot: 5, name: "山田 太郎", email: "taro@example.com" }
].map((reservation) => {
  const date = new Date(demoMonday);
  date.setDate(date.getDate() + reservation.day);
  return { ...reservation, date };
});

function createTextElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function openReservationDialog(date, slot) {
  byId("reservation-dialog").querySelector("form").reset();
  byId("selected-slot").textContent = `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日（${weekdays[(date.getDay() + 6) % 7]}） ${timeAt(slot)}–${timeAt(slot + 1)}`;
  byId("reservation-dialog").showModal();
}

function renderCalendar() {
  const monday = dateAt(0);
  const friday = dateAt(4);
  byId("week-label").textContent = `${shortDate(monday)} ～ ${shortDate(friday)} (${monday.getFullYear()}${monday.getFullYear() !== friday.getFullYear() ? `–${friday.getFullYear()}` : ""})`;
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
      const reservation = demoReservations.find((item) => item.date.getTime() === date.getTime() && item.slot === slot);
      const cell = document.createElement("td");
      if (reservation) {
        cell.className = "reserved";
        cell.textContent = reservation.name;
        cell.setAttribute("aria-label", `${shortDate(date)} ${timeAt(slot)} 予約済み ${reservation.name}（仮データ）`);
      } else if ((day === 3 && slot < 8) || (day === 1 && slot >= 3 && slot <= 5) || (day === 4 && slot >= 14)) {
        cell.className = "busy";
        cell.textContent = "予定あり";
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
    top.append(createTextElement("span", "確定", "stamp"), detail);
    const actions = createTextElement("div", "", "card-actions");
    const cancel = createTextElement("button", "キャンセル", "button");
    cancel.type = "button";
    cancel.disabled = true;
    cancel.title = "STEP 2以降に実装予定";
    actions.append(cancel);
    card.append(top, actions);
    cards.append(card);
  });
  byId("reservation-list").replaceChildren(cards);
  byId("reservation-count").textContent = `${demoReservations.length}件`;
}

function showSelectedFiles(files) {
  // 名前のみ表示し、ファイルの内容にはアクセスしません。
  const selected = Array.from(files);
  const isCalendarFile = (file) => /\.ics$/i.test(file.name);
  if (!selected.length) return;
  if (!selected.every(isCalendarFile)) {
    byId("import-status").textContent = ".ics ファイルを選択してください。予定はまだ読み込まれていません。";
    return;
  }
  byId("import-status").textContent = `選択済み：${selected.map((file) => file.name).join("、")}（${selected.length}ファイル） · ICS解析は未実装です`;
}

document.querySelector(".close-button").addEventListener("click", () => {
  byId("reservation-dialog").close();
});
byId("today").textContent = today.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric", weekday: "short" });
byId("previous-week").addEventListener("click", () => { displayedMonday.setDate(displayedMonday.getDate() - 7); renderCalendar(); });
byId("next-week").addEventListener("click", () => { displayedMonday.setDate(displayedMonday.getDate() + 7); renderCalendar(); });
byId("current-week").addEventListener("click", () => { displayedMonday = startOfWeek(new Date()); renderCalendar(); });
byId("choose-file").addEventListener("click", () => byId("ics-file").click());
byId("ics-file").addEventListener("change", (event) => showSelectedFiles(event.target.files));
byId("clear-files").addEventListener("click", () => {
  byId("ics-file").value = "";
  byId("import-status").textContent = "未読み込み · ファイル選択をクリアしました。仮データは引き続き表示しています。";
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

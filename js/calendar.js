"use strict";
// 日付用DateはUTCの年月日を東京の暦日として使用。ブラウザのTZに依存しない。
window.Calendar = (() => {
  const dayMs = 86400000;
  function today() {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const get = (type) => Number(parts.find((p) => p.type === type).value);
    return new Date(Date.UTC(get('year'), get('month') - 1, get('day')));
  }
  function startOfWeek(date) {
    return new Date(date.getTime() - ((date.getUTCDay() + 6) % 7) * dayMs);
  }
  function slotRange(date, slot) {
    const start = date.getTime() + (9 * 60 + slot * 30 - 540) * 60000;
    return { start, end: start + 1800000 };
  }
  const overlaps = (event, range) => event.start < range.end && event.end > range.start;
  function availability(date, slot, events, reservations) {
    const range = slotRange(date, slot);
    const busy = events.filter((event) => event.status !== 'CANCELLED' && overlaps(event, range));
    const reserved = reservations.find((event) => event.status === 'confirmed' && overlaps(event, range));
    return { state: reserved ? 'reserved' : busy.length ? 'busy' : 'available', busy, reservation: reserved };
  }
  return { today, startOfWeek, slotRange, overlaps, availability };
})();

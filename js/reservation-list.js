"use strict";
// 表示専用。入力配列・予約オブジェクト・保存領域は変更しない。
window.ReservationList = (() => {
  const PAGE_SIZE = 20;
  const dateKey = (timestamp) => new Date(timestamp + 9 * 3600000).toISOString().slice(0, 10);
  function select(items, {status = 'all', query = '', date = '', page = 1} = {}) {
    const term = query.trim().toLowerCase();
    const filtered = items.filter(item => status === 'all' || item.status === status)
      .filter(item => !term || item.name.toLowerCase().includes(term) || item.email.toLowerCase().includes(term))
      .filter(item => !date || dateKey(item.start) === date)
      .sort((a, b) => a.start - b.start || a.createdAt - b.createdAt);
    const total = filtered.length;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const current = Math.min(pages, Math.max(1, page));
    const offset = (current - 1) * PAGE_SIZE;
    return {items: filtered.slice(offset, offset + PAGE_SIZE), total, pages, page: current,
      first: total ? offset + 1 : 0, last: Math.min(offset + PAGE_SIZE, total)};
  }
  return {select, dateKey, PAGE_SIZE};
})();

// 달력 화면 스크립트 (/calendar)
// - /api/calendar?month=YYYYMM&status= 로 한 달 요약을 받아 날짜 칸에 사진 수(색 진하기)·📖·첫/마지막 시각·이동 거리를 그린다.
// - 날짜를 고르면 자세히(시각·거리·일기 제목)와 지도 / 여행기 / 일기 링크를 보여 준다.
// - 키보드: Tab 은 고른 날 하나에만 멈추고 ←→ 하루, ↑↓ 한 주, Home/End 그 주 처음·끝, PageUp/PageDown 한 달.
//   달 밖으로 넘어가면 그달을 불러온다.
// - 주소 ?month=YYYYMM&day=YYYYMMDD&status= 로 기억한다.
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("cal-config").textContent);
  const $ = (id) => document.getElementById(id);
  const grid = $("cal-grid"), detail = $("cal-detail"), total = $("cal-total");
  const statusInputs = [...document.querySelectorAll('input[name="status"]')];
  const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

  let month = null;        // 'YYYYMM'
  let days = {};           // base_dt → 요약
  let selected = null;     // 고른 날 'YYYYMMDD'
  let requestSeq = 0;

  // ── 날짜 계산 (브라우저 현지 날짜) ──
  const pad = (n) => String(n).padStart(2, "0");
  const ymd = (d) => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
  const toDate = (dt) => new Date(+dt.slice(0, 4), +dt.slice(4, 6) - 1, +dt.slice(6, 8));
  const monthOf = (dt) => dt.slice(0, 6);
  const today = () => ymd(new Date());
  function addDays(dt, n) { const d = toDate(dt); d.setDate(d.getDate() + n); return ymd(d); }
  function addMonths(dt, n) {
    const d = toDate(dt), day = d.getDate();
    const t = new Date(d.getFullYear(), d.getMonth() + n, 1);
    const last = new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate();
    t.setDate(Math.min(day, last));           // 31일 → 다음 달 말일
    return ymd(t);
  }
  const label = (dt) => { const d = toDate(dt); return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEK[d.getDay()]})`; };

  const statusFilter = () => statusInputs.filter((i) => i.checked).map((i) => i.value);
  const isDefaultFilter = () =>
    statusFilter().slice().sort().join() === config.defaultStatuses.slice().sort().join();
  const statusQuery = () => (isDefaultFilter() ? "" : `&status=${statusFilter().join(",")}`);

  async function api(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (res.status === 401) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
      throw new Error("로그인이 필요합니다.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `요청 실패 (HTTP ${res.status})`);
    return data;
  }

  // 사진 수 → 색 단계 (0 은 색 없음)
  const heat = (n) => (n >= 20 ? 4 : n >= 10 ? 3 : n >= 4 ? 2 : n >= 1 ? 1 : 0);
  const km = (v) => (v >= 10 ? `${Math.round(v)}km` : `${v.toFixed(1)}km`);

  // ============================================================
  // 불러오기
  // ============================================================
  async function load(m, pick) {
    month = m;
    $("cal-title").textContent = `${m.slice(0, 4)}년 ${+m.slice(4, 6)}월`;
    selected = pick && monthOf(pick) === m ? pick : selected && monthOf(selected) === m ? selected : null;
    days = {};
    render();
    if (statusFilter().length === 0) {
      total.textContent = "사진 상태를 하나 이상 골라 주세요.";
      return;
    }
    const seq = ++requestSeq;
    total.textContent = "불러오는 중…";
    let data;
    try {
      data = await api(`${config.apiUrl}?month=${m}&status=${statusFilter().join(",")}`);
    } catch (e) {
      if (seq === requestSeq) total.textContent = `불러오지 못했습니다: ${e.message}`;
      return;
    }
    if (seq !== requestSeq) return;
    days = data.days;
    const t = data.totals;
    total.textContent = t.photos || t.diaries
      ? `사진 ${t.photos}장 · 사진 찍은 날 ${t.days_with_photos}일 · 일기 ${t.diaries}편 · 이동 ${km(t.km)}`
      : "이달에는 사진도 일기도 없습니다.";
    render();
  }

  function updateUrl() {
    const q = `?month=${month}${selected ? `&day=${selected}` : ""}${statusQuery()}`;
    history.replaceState(null, "", q);
  }

  // ============================================================
  // 그리기
  // ============================================================
  function render() {
    grid.replaceChildren();
    const first = toDate(`${month}01`);
    const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const todayDt = today();
    let row = null;
    const cells = first.getDay() + lastDay;
    for (let i = 0; i < Math.ceil(cells / 7) * 7; i++) {
      if (i % 7 === 0) {
        row = document.createElement("div");
        row.className = "cal-row";
        row.setAttribute("role", "row");
        grid.append(row);
      }
      const n = i - first.getDay() + 1;
      if (n < 1 || n > lastDay) {                  // 이달 밖 빈칸
        const blank = document.createElement("span");
        blank.className = "cal-day is-blank";
        blank.setAttribute("role", "gridcell");
        row.append(blank);
        continue;
      }
      const dt = `${month}${pad(n)}`;
      row.append(dayCell(dt, days[dt], i % 7, dt === todayDt));
    }
    syncTabStop();
    renderDetail();
    updateUrl();
  }

  function dayCell(dt, d, dow, isToday) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.dt = dt;
    btn.setAttribute("role", "gridcell");
    btn.className = `cal-day h${heat(d?.count || 0)}${isToday ? " is-today" : ""}${dt === selected ? " is-selected" : ""}` +
      `${dow === 0 ? " sun" : dow === 6 ? " sat" : ""}`;
    const parts = [label(dt)];
    const top = document.createElement("span");
    top.className = "cd-top";
    const num = document.createElement("span");
    num.className = "cd-num";
    num.textContent = +dt.slice(6, 8);
    top.append(num);
    if (d?.has_diary) {
      const di = document.createElement("span");
      di.className = "cd-diary";
      di.textContent = "📖";
      top.append(di);
      parts.push("일기 있음");
    }
    btn.append(top);
    if (d?.count) {
      add(btn, "cd-count", `${d.count}장`);
      add(btn, "cd-time", d.first === d.last ? d.first : `${d.first}–${d.last}`);
      if (d.km > 0) add(btn, "cd-km", km(d.km));
      parts.push(`사진 ${d.count}장`, `${d.first}~${d.last}`);
      if (d.km > 0) parts.push(`이동 ${km(d.km)}`);
    }
    btn.setAttribute("aria-label", parts.join(", "));
    btn.addEventListener("click", () => select(dt, false));
    return btn;
  }

  function add(parent, cls, text) {
    const s = document.createElement("span");
    s.className = cls;
    s.textContent = text;
    parent.append(s);
  }

  // Tab 정지점: 고른 날 → 오늘 → 1일
  function syncTabStop() {
    const cells = [...grid.querySelectorAll("button.cal-day")];
    const stop = cells.find((c) => c.dataset.dt === selected) || cells.find((c) => c.classList.contains("is-today")) || cells[0];
    for (const c of cells) c.tabIndex = c === stop ? 0 : -1;
  }

  // ── 날짜 고르기 ──
  function select(dt, focus) {
    if (monthOf(dt) !== month) {              // 다른 달로 넘어가면 그달을 불러와서 고른다
      load(monthOf(dt), dt).then(() => focus && cellOf(dt)?.focus());
      selected = dt;
      return;
    }
    selected = dt;
    for (const c of grid.querySelectorAll("button.cal-day")) c.classList.toggle("is-selected", c.dataset.dt === dt);
    syncTabStop();
    renderDetail();
    updateUrl();
    if (focus) cellOf(dt)?.focus();
  }
  const cellOf = (dt) => grid.querySelector(`button.cal-day[data-dt="${dt}"]`);

  // ── 자세히 ──
  function renderDetail() {
    detail.replaceChildren();
    if (!selected) {
      add(detail, "muted small", "날짜를 고르면 그날 기록이 여기에 나옵니다.");
      return;
    }
    const d = days[selected];
    const h = document.createElement("h2");
    h.className = "cdd-date";
    h.textContent = label(selected);
    detail.append(h);

    const list = document.createElement("dl");
    list.className = "cdd-list";
    const row = (k, v) => {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      list.append(dt, dd);
    };
    row("사진", d?.count ? `${d.count}장` : "없음");
    if (d?.count) {
      row("첫 사진", d.first);
      row("마지막 사진", d.last);
      row("이동 거리", d.km > 0 ? km(d.km) : "위치 있는 사진이 2장 미만");
    }
    row("일기", d?.has_diary ? d.diary_title || "제목 없음" : "없음");
    detail.append(list);

    const links = document.createElement("div");
    links.className = "cdd-links";
    const link = (text, href, primary) => {
      const a = document.createElement("a");
      a.href = href;
      a.textContent = text;
      a.className = primary ? "btn-small" : "btn-small btn-ghost";
      links.append(a);
    };
    const sq = statusQuery();
    if (d?.count) link("지도에서 보기", `${config.mapPage}?start=${selected}&end=${selected}${sq}`, true);
    if (d?.count || d?.has_diary) link("여행기", `${config.storyPage}?start=${selected}&end=${selected}${sq}`);
    if (d?.has_diary) link("일기 읽기", `${config.diaryPage}?date=${selected}&open=1`);
    link(d?.has_diary ? "일기 고치기" : "일기 쓰기", `${config.diaryPage}?date=${selected}&write=1`);
    detail.append(links);
  }

  // ============================================================
  // 키보드 · 버튼
  // ============================================================
  grid.addEventListener("keydown", (e) => {
    const cell = e.target.closest("button.cal-day");
    if (!cell || e.altKey || e.ctrlKey || e.metaKey) return;
    const dt = cell.dataset.dt, dow = toDate(dt).getDay();
    const moves = {
      ArrowLeft: () => addDays(dt, -1), ArrowRight: () => addDays(dt, 1),
      ArrowUp: () => addDays(dt, -7), ArrowDown: () => addDays(dt, 7),
      Home: () => addDays(dt, -dow), End: () => addDays(dt, 6 - dow),
      PageUp: () => addMonths(dt, -1), PageDown: () => addMonths(dt, 1),
    };
    if (!(e.key in moves)) return;
    e.preventDefault();
    select(moves[e.key](), true);
  });

  $("cal-prev").addEventListener("click", () => load(monthOf(addMonths(`${month}01`, -1))));
  $("cal-next").addEventListener("click", () => load(monthOf(addMonths(`${month}01`, 1))));
  $("cal-today").addEventListener("click", () => load(monthOf(today()), today()));
  for (const input of statusInputs) input.addEventListener("change", () => load(month, selected));

  // ── 시작: 주소의 달·날짜·상태 (없으면 이번 달, 오늘) ──
  (function init() {
    const q = new URLSearchParams(location.search);
    if (q.get("status")) {
      const list = q.get("status").toUpperCase().split(",");
      for (const i of statusInputs) i.checked = list.includes(i.value);
    }
    const m = /^\d{6}$/.test(q.get("month") || "") ? q.get("month") : monthOf(today());
    const d = /^\d{8}$/.test(q.get("day") || "") ? q.get("day") : null;
    load(m, d);
  })();
})();

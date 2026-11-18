// 여행기 화면 스크립트 (/story)
// - 기간(+사진 상태)으로 /api/story 를 불러와, 사진이나 일기가 있는 날을 날짜순으로 이어 붙인다.
// - 하루 = 날짜 머리 → 그날 일기(마크다운) → 동선 지도(순번 마커 + 이동 경로) → 사진(촬영순)
//   사진 중 설명이 있는 것은 사진과 설명을 나란히 크게, 설명이 없는 사진은 이어지는 것끼리 작은 타일로 묶는다.
// - 지도는 화면에 보일 때 그린다(IntersectionObserver) — 날이 많아도 처음 열 때 무겁지 않게.
// - 사진을 누르면 크게 보기(dayview.js 라이트박스). ← → 로 기간 전체의 사진을 촬영순으로 넘긴다.
// - 'PDF로 저장': 모든 날의 지도·사진을 미리 그리고 불러온 뒤 인쇄 창을 연다(인쇄용 CSS, A4 폭에 맞춤).
// - '백업 내보내기': 같은 기간·상태로 /backup/download zip 을 내려받는다.
// - 주소 ?start=&end=&status= 로 기간·상태를 기억한다 (지도 화면의 '여행기' 버튼이 같은 형식으로 연다).
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("story-config").textContent);
  const $ = (id) => document.getElementById(id);
  const startInput = $("start"), endInput = $("end");
  const statusInputs = [...document.querySelectorAll('input[name="status"]')];
  const daysBox = $("story-days"), toc = $("story-toc"), summary = $("story-summary");

  let allPhotos = [];         // 기간 전체 사진 (촬영순) — 크게 보기에서 날을 넘어 이어 보기
  let current = null;         // 지금 보고 있는 조건 { start, end, days, diaries }
  const dayMaps = new Map();  // base_dt → 동선 지도 (그린 것만)
  let requestSeq = 0;

  // ── 날짜 ──
  const toInput = (dt) => `${dt.slice(0, 4)}-${dt.slice(4, 6)}-${dt.slice(6, 8)}`;
  const fromInput = (v) => v.replaceAll("-", "");
  const ymd = (d) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  const shortDate = (dt) => `${+dt.slice(4, 6)}.${+dt.slice(6, 8)}`;
  function defaultRange() {   // 지도 화면과 같은 기본값: 이번 달 1일 ~ 오늘
    const now = new Date();
    return { start: ymd(new Date(now.getFullYear(), now.getMonth(), 1)), end: ymd(now) };
  }

  const statusFilter = () => statusInputs.filter((i) => i.checked).map((i) => i.value);
  const isDefaultFilter = () =>
    statusFilter().slice().sort().join() === config.defaultStatuses.slice().sort().join();

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

  // ============================================================
  // 불러오기
  // ============================================================
  async function load(start, end) {
    if (start > end) [start, end] = [end, start];
    startInput.value = toInput(start);
    endInput.value = toInput(end);
    const q = new URLSearchParams({ start, end });
    if (!isDefaultFilter()) q.set("status", statusFilter().join(","));
    history.replaceState(null, "", `?${q}`);

    clear();
    if (statusFilter().length === 0) {
      summary.textContent = "사진 상태를 하나 이상 골라 주세요.";
      return;
    }
    const seq = ++requestSeq;
    summary.textContent = "불러오는 중…";
    let data;
    try {
      data = await api(`${config.apiUrl}?start=${start}&end=${end}&status=${statusFilter().join(",")}`);
    } catch (e) {
      if (seq === requestSeq) summary.textContent = `불러오지 못했습니다: ${e.message}`;
      return;
    }
    if (seq !== requestSeq) return;
    render(data.days, start, end);
  }

  function clear() {
    for (const m of dayMaps.values()) m.remove();
    dayMaps.clear();
    mapObserver.disconnect();
    daysBox.replaceChildren();
    toc.replaceChildren();
    allPhotos = [];
    current = null;
  }

  // ============================================================
  // 그리기
  // ============================================================
  function render(days, start, end) {
    const photoCount = days.reduce((n, d) => n + d.photos.length, 0);
    const diaryCount = days.filter((d) => d.diary).length;
    current = { start, end, days: days.length, photos: photoCount, diaries: diaryCount };
    if (days.length === 0) {
      summary.textContent = "이 기간에는 사진도 일기도 없습니다.";
      return;
    }
    summary.textContent = `${TPDay.longDate(start).replace(/ \S+요일$/, "")} ~ ${TPDay.longDate(end).replace(/ \S+요일$/, "")}` +
      ` · ${days.length}일 · 사진 ${photoCount}장 · 일기 ${diaryCount}편`;

    for (const day of days) {
      const offset = allPhotos.length;      // 기간 전체에서 이 날 첫 사진의 위치
      allPhotos.push(...day.photos);
      daysBox.append(dayBlock(day, offset));
      // 날짜 바로가기
      const a = document.createElement("a");
      a.href = `#d-${day.base_dt}`;
      a.className = "toc-item";
      a.textContent = shortDate(day.base_dt) + (day.diary ? " 📖" : "");
      a.title = `${TPDay.longDate(day.base_dt)} · 사진 ${day.photos.length}장${day.diary ? " · 일기 있음" : ""}`;
      toc.append(a);
    }
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // 하루 블록
  function dayBlock(day, offset) {
    const sec = el("section", "story-day");
    sec.id = `d-${day.base_dt}`;

    // 머리: 날짜 · 사진 수 · 링크
    const head = el("header", "sd-head");
    const h2 = el("h2", "sd-date", TPDay.longDate(day.base_dt));
    const meta = el("div", "sd-meta");
    const st = day.stats;
    let info = `사진 ${day.photos.length}장`;
    if (st && st.count) info += ` · ${st.first === st.last ? st.first : `${st.first}–${st.last}`}`;
    if (st && st.km > 0) info += ` · 이동 ${st.km >= 10 ? Math.round(st.km) : st.km}km`;
    meta.append(el("span", "muted small sd-stats", info));
    const toMap = el("a", "sd-link", "지도에서 보기");
    toMap.href = TPDay.mapUrl(day.base_dt);
    const toDiary = el("a", "sd-link", day.diary ? "일기 고치기" : "이날 일기 쓰기");
    toDiary.href = `${config.diaryPage}?date=${day.base_dt}&write=1`;
    meta.append(day.photos.length ? toMap : "", toDiary);
    head.append(h2, meta);
    sec.append(head);

    // 그날 일기
    if (day.diary) {
      const art = el("article", "sd-diary");
      if (day.diary.title) art.append(el("h3", "sd-diary-title", day.diary.title));
      const body = el("div", "md-body");
      body.innerHTML = day.diary.html;      // 서버에서 nh3 로 살균한 HTML
      art.append(body);
      sec.append(art);
    }

    // 동선 지도 (보일 때 그린다)
    if (day.photos.some((p) => p.lat !== null)) {
      const mapEl = el("div", "sd-map");
      mapEl.dataset.dt = day.base_dt;
      mapEl.setAttribute("role", "application");
      mapEl.setAttribute("aria-label", `${TPDay.longDate(day.base_dt)} 동선 지도`);
      pendingMaps.set(mapEl, { photos: day.photos, offset });
      mapObserver.observe(mapEl);
      sec.append(mapEl);
    }

    // 사진: 설명 있는 사진은 크게, 설명 없는 사진은 이어지는 것끼리 타일 묶음
    const list = el("div", "sd-photos");
    let tiles = null;
    day.photos.forEach((p, i) => {
      const index = offset + i;
      if (p.note) {
        tiles = null;
        list.append(notedPhoto(p, i + 1, index));
      } else {
        if (!tiles) { tiles = el("div", "sd-tiles"); list.append(tiles); }
        tiles.append(photoButton(p, i + 1, index, "sd-tile"));
      }
    });
    if (day.photos.length) sec.append(list);
    return sec;
  }

  // 사진 버튼 (순번 배지 + 상태 테두리), 누르면 크게 보기
  function photoButton(p, seq, index, cls) {
    const btn = el("button", `${cls} st-${p.status}${p.has_note ? " has-note" : ""}`);
    btn.type = "button";
    btn.dataset.index = index;
    btn.title = `${seq}번째 · ${p.photo_at.slice(11)}${p.lat === null ? " · 위치 없음" : ""}`;
    const img = el("img");
    img.src = cls === "sd-tile" ? p.mini_url || p.thumb_url : p.thumb_url;
    img.alt = `${seq}번째 사진`;
    img.loading = "lazy";
    btn.append(img, el("span", "seq", String(seq)));
    if (cls === "sd-tile") btn.append(el("span", "time", p.photo_at.slice(11)));
    btn.addEventListener("click", () => openPhoto(index));
    return btn;
  }

  // 설명 있는 사진: 왼쪽 사진, 오른쪽 시각·제목·설명
  function notedPhoto(p, seq, index) {
    const row = el("figure", "sd-noted");
    row.append(photoButton(p, seq, index, "sd-noted-img"));
    const cap = el("figcaption", "sd-noted-text");
    cap.append(el("div", "sd-time muted small", `${seq}번째 · ${p.photo_at.slice(11)}${p.lat === null ? " · 위치 없음" : ""}`));
    if (p.note.title) cap.append(el("h4", "sd-note-title", p.note.title));
    const body = el("div", "md-body");
    body.innerHTML = p.note.html;           // 서버에서 nh3 로 살균한 HTML
    cap.append(body);
    row.append(cap);
    return row;
  }

  // ── 동선 지도: 화면 가까이 오면 그린다 ──
  const pendingMaps = new Map();   // 지도 칸 → { photos, offset }
  const mapObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const mapEl = entry.target;
      const job = pendingMaps.get(mapEl);
      mapObserver.unobserve(mapEl);
      pendingMaps.delete(mapEl);
      if (!job) continue;
      const m = TPDay.dayMap(mapEl, job.photos, { onSelect: (i) => openPhoto(job.offset + i) });
      if (m) dayMaps.set(mapEl.dataset.dt, m);
    }
  }, { rootMargin: "300px 0px" });

  // ── 크게 보기: 기간 전체 사진을 촬영순으로 넘긴다 ──
  function openPhoto(index) {
    TPDay.lightbox(allPhotos, index, {
      caption: (p, i) => {
        const note = p.note && p.note.title ? ` · ${p.note.title}` : "";
        return `${i + 1} / ${allPhotos.length} · ${p.photo_at}${note}`;
      },
      onChange: (i) => highlight(i),
    });
  }

  // 크게 보며 넘긴 사진을 본문에서도 강조하고, 그날 지도 마커도 강조한다 (닫으면 그 자리가 보이게)
  function highlight(index) {
    for (const b of daysBox.querySelectorAll(".is-selected")) b.classList.remove("is-selected");
    const btn = daysBox.querySelector(`[data-index="${index}"]`);
    if (!btn) return;
    btn.classList.add("is-selected");
    btn.scrollIntoView({ block: "nearest" });
    const p = allPhotos[index];
    const m = dayMaps.get(p.base_dt);
    if (m) {
      const dayStart = allPhotos.findIndex((x) => x.base_dt === p.base_dt);
      m.select(index - dayStart);
    }
  }

  // ============================================================
  // PDF 로 저장 — 브라우저 인쇄 창의 'PDF로 저장'
  // - 화면에 아직 안 그린 지도·안 불러온 사진이 있으면 PDF 에 빠지므로, 먼저 모두 그리고 다 불러올 때까지 기다린다.
  // - 인쇄하는 동안 본문 폭을 A4 폭에 맞춰(body.printing) 지도를 그 크기로 다시 맞춘다.
  // ============================================================
  const pdfBtn = $("pdf-btn");
  async function printStory() {
    if (!current || current.days === 0) { summary.textContent = "PDF로 저장할 내용이 없습니다."; return; }
    pdfBtn.disabled = true;
    pdfBtn.textContent = "준비 중…";
    document.body.classList.add("printing");
    try {
      for (const [mapEl, job] of [...pendingMaps]) {           // 아직 안 그린 지도
        mapObserver.unobserve(mapEl);
        pendingMaps.delete(mapEl);
        const m = TPDay.dayMap(mapEl, job.photos, { onSelect: (i) => openPhoto(job.offset + i) });
        if (m) dayMaps.set(mapEl.dataset.dt, m);
      }
      for (const m of dayMaps.values()) m.fit();             // 인쇄 폭에 맞춰 다시 맞추기
      for (const img of daysBox.querySelectorAll("img")) img.loading = "eager";
      await waitImages(8000);                                 // 사진 + 지도 타일
      window.print();
    } finally {
      document.body.classList.remove("printing");
      for (const m of dayMaps.values()) m.fit();
      pdfBtn.disabled = false;
      pdfBtn.textContent = "PDF로 저장";
    }
  }

  // 본문의 모든 이미지(사진·지도 타일)가 다 불러와질 때까지 (최대 timeout ms)
  async function waitImages(timeout) {
    const until = performance.now() + timeout;
    await new Promise((r) => setTimeout(r, 300));             // 지도가 타일 요청을 시작할 시간
    while (performance.now() < until) {
      const pending = [...daysBox.querySelectorAll("img")].filter((img) => !img.complete);
      if (pending.length === 0) return;
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  pdfBtn.addEventListener("click", printStory);

  // ============================================================
  // 백업 내보내기 — 지금 기간·상태 그대로 zip
  // ============================================================
  const backupDlg = $("backup-dlg");
  function openBackup() {
    if (!current) return;
    $("bk-range").textContent = `${TPDay.longDate(current.start)} ~ ${TPDay.longDate(current.end)}`;
    $("bk-summary").textContent = current.photos || current.diaries
      ? `사진 ${current.photos}장 · 일기 ${current.diaries}편을 zip 파일 하나로 내려받습니다.` +
        (current.photos > 300 ? " 사진이 많아 시간이 조금 걸릴 수 있습니다." : "")
      : "이 기간에는 내보낼 사진이나 일기가 없습니다.";
    $("bk-download").hidden = !(current.photos || current.diaries);
    updateBackupLink();
    backupDlg.showModal();
  }
  function updateBackupLink() {
    if (!current) return;
    const q = new URLSearchParams({ start: current.start, end: current.end });
    if (!isDefaultFilter()) q.set("status", statusFilter().join(","));
    if (!$("bk-exif").checked) q.set("exif", "0");
    $("bk-download").href = `${config.backupUrl}?${q}`;
  }
  $("backup-btn").addEventListener("click", openBackup);
  $("bk-exif").addEventListener("change", updateBackupLink);
  $("bk-download").addEventListener("click", () => setTimeout(() => backupDlg.close(), 300));
  backupDlg.addEventListener("click", (e) => {
    if (e.target === backupDlg || e.target.closest("[data-close]")) backupDlg.close();
  });

  // ============================================================
  // 조건 바꾸기
  // ============================================================
  $("story-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (startInput.value && endInput.value) load(fromInput(startInput.value), fromInput(endInput.value));
  });
  for (const input of statusInputs) {
    input.addEventListener("change", () => load(fromInput(startInput.value), fromInput(endInput.value)));
  }

  // ── 시작: 주소의 기간·상태 (없으면 이번 달 1일 ~ 오늘) ──
  (function init() {
    const q = new URLSearchParams(location.search);
    if (q.get("status")) {
      const list = q.get("status").toUpperCase().split(",");
      for (const i of statusInputs) i.checked = list.includes(i.value);
    }
    const valid = (v) => /^\d{8}$/.test(v || "");
    const r = valid(q.get("start")) && valid(q.get("end"))
      ? { start: q.get("start"), end: q.get("end") }
      : defaultRange();
    load(r.start, r.end);
  })();
})();

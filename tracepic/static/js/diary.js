// 일기 화면 스크립트 — 기록 카드가 원형으로 늘어선 3D 링
//
// 배치 방식
// - 링에는 최소 MIN_SLOTS 장의 카드 자리가 있다. 기록(entry)은 날짜순으로 앞자리부터 채우고,
//   남는 자리는 빈 종이(ghost)로 채워 링 모양을 유지한다.
// - 카드는 링 중심에서 바깥을 향해 '세로로 꽂힌' 모양(반지름 방향)으로 서 있다 → 첨부 이미지의 느낌.
// - 가운데(앞)에 온 기록 카드는 정면으로 돌아서며 앞으로 나오고, 양옆 카드는 살짝 벌어진다.
//
// 조작
// - 드래그(관성 포함), 마우스 휠, ← → (PageUp/PageDown 10장, Home/End), 슬라이더
// - 가운데 카드 클릭/Enter → 읽기, 다른 카드 클릭 → 그 카드로 회전, N → 새 기록
//
// 읽기 창: 그날 사진이 있으면 오른쪽에 '이날의 동선'(순번 마커 + 이동 경로 지도, dayview.js)과 사진 줄을 보여 준다.
//          사진·마커를 누르면 크게 보기(← → 로 넘기기), '지도에서 크게 보기'는 지도 화면의 그날 조회로 간다.
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("diary-config").textContent);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const $ = (id) => document.getElementById(id);

  const stage = $("stage"), ring = $("ring");
  const yearSelect = $("year"), scrub = $("scrub");

  // ── 링 모양 설정 ──
  const MIN_SLOTS = 96;        // 기록이 적어도 링이 비어 보이지 않도록 채울 최소 자리 수
  const FACE_ANGLE = -78;      // 카드가 반지름 방향에서 틀어진 각도 (−90 이면 완전히 옆을 봄)
  const SPACING = 0.36;        // 카드 사이 간격(호의 길이) ÷ 카드 폭 — 클수록 틈 사이로 바닥이 보인다 (0.30 → 0.36, +20%)
  const FRONT_Y = 0.47;        // 앞 카드 중심이 놓일 높이 (무대 높이 대비)
  const PX_PER_CARD = 34;      // 드래그 몇 px 에 카드 한 장 넘어가는지
  const TILT = 6;              // 링을 내려다보는 각도 — 작을수록 수평에 가깝게 본다 (CSS 변수 --tilt 로 전달)

  // ── 상태 ──
  let entries = [];            // [{ base_dt, title, excerpt, updated_at }] 날짜 오름차순
  let cards = [];              // 카드 DOM (자리 순서)
  let slots = MIN_SLOTS;
  let step = 360 / slots;      // 자리 하나의 각도
  let radius = 600;
  let rot = 0;                 // 링의 현재 회전각(deg) — 앞에 오는 자리 = -rot / step
  let active = -1;             // 앞에 선 기록 번호 (기록이 없으면 -1)
  let currentYear = null;
  let reading = null;          // 읽기 창에 열린 기록(전체 데이터)

  // ============================================================
  // 서버 통신
  // ============================================================
  async function api(url, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.method && options.method !== "GET") {
      headers["X-CSRF-Token"] = csrfToken;
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
      throw new Error("로그인이 필요합니다.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || `요청 실패 (HTTP ${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  const entryUrl = (dt) => `${config.apiUrl}/${dt}`;

  // ============================================================
  // 날짜 표시
  // ============================================================
  const DOW = ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];
  const toDate = (dt) => new Date(+dt.slice(0, 4), +dt.slice(4, 6) - 1, +dt.slice(6, 8));
  const longDate = (dt) => `${dt.slice(0, 4)}년 ${+dt.slice(4, 6)}월 ${+dt.slice(6, 8)}일 ${DOW[toDate(dt).getDay()]}`;
  const toInput = (dt) => `${dt.slice(0, 4)}-${dt.slice(4, 6)}-${dt.slice(6, 8)}`;
  const fromInput = (v) => v.replaceAll("-", "");
  function todayDt() {
    const d = new Date(), p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`;
  }

  // ============================================================
  // 링 만들기
  // ============================================================
  function build() {
    slots = Math.max(MIN_SLOTS, entries.length + 12);   // 기록이 많으면 자리를 늘린다 (끝과 처음 사이 여백 12장)
    step = 360 / slots;
    const cardW = parseFloat(getComputedStyle(stage).getPropertyValue("--card-w")) || 200;
    // 카드 사이 간격(호의 길이)이 카드 폭의 SPACING 배가 되도록 반지름을 정한다
    radius = Math.max(cardW * 3, (slots * cardW * SPACING) / (2 * Math.PI));
    stage.style.setProperty("--radius", `${radius}px`);
    stage.style.setProperty("--perspective", `${Math.round(radius * 2.1)}px`);
    // 링을 기울이면 앞쪽이 R·sin(기울기) 만큼 내려온다 → 앞 카드가 FRONT_Y 높이에 오도록 링 중심을 올린다
    const ringTop = stage.clientHeight * FRONT_Y - radius * Math.sin((TILT * Math.PI) / 180);
    stage.style.setProperty("--ring-top", `${ringTop}px`);
    stage.style.setProperty("--tilt", `${-TILT}deg`);

    ring.replaceChildren();
    cards = [];
    const frag = document.createDocumentFragment();
    for (let i = 0; i < slots; i++) {
      const card = document.createElement("div");
      card.className = "card";
      const entry = entries[i];
      if (entry) {
        card.classList.add("is-entry");
        card.dataset.index = i;
        card.append(cardFace(entry));
      } else {
        card.classList.add("is-ghost");
      }
      frag.append(card);
      cards.push(card);
    }
    ring.append(frag);

    const hasEntries = entries.length > 0;
    ring.classList.toggle("is-idle", !hasEntries);
    $("empty").hidden = hasEntries;
    scrub.max = Math.max(0, entries.length - 1);
    scrub.disabled = entries.length < 2;
    layout();
  }

  // 카드 앞면 (textContent 로 넣어 기록 내용에 HTML 이 있어도 안전)
  function cardFace(entry) {
    const face = document.createElement("div");
    face.className = "card-face";
    const d = toDate(entry.base_dt);
    const parts = [
      ["c-year", `${entry.base_dt.slice(0, 4)} · ${entry.base_dt.slice(4, 6)}`],
      ["c-day", String(d.getDate())],
      ["c-dow", DOW[d.getDay()]],
      ["c-title", entry.title],
      ["c-text", entry.excerpt],
    ];
    for (const [cls, text] of parts) {
      if (!text) continue;
      const el = document.createElement("div");
      el.className = cls;
      el.textContent = text;
      face.append(el);
    }
    return face;
  }

  // ============================================================
  // 카드 배치 — 앞에 선 카드 기준으로 양옆을 벌린다
  // ============================================================
  function layout() {
    const cardW = parseFloat(getComputedStyle(stage).getPropertyValue("--card-w")) || 200;
    // 앞 카드가 정면으로 돌면 폭만큼 공간이 필요 → 그만큼의 각도를 양옆으로 벌린다
    const gap = active >= 0 ? ((cardW * 0.62) / radius) * (180 / Math.PI) : 0;
    const lift = cardW * 0.55;
    for (let i = 0; i < slots; i++) {
      const base = i * step;
      const card = cards[i];
      const isActive = i === active;
      card.classList.toggle("is-active", isActive);
      if (isActive) {
        // 정면을 보고, 링 기울기를 되돌려 똑바로 선다
        card.style.transform = `rotateY(${base}deg) translateZ(${radius + lift}px) rotateX(${TILT}deg)`;
        continue;
      }
      // 앞 카드와의 각도 차(−180~180)에 따라 벌림 정도를 줄여, 링 뒤쪽에서는 겹치지 않게 한다
      let d = (((i - Math.max(active, 0)) * step) % 360 + 540) % 360 - 180;
      const spread = active >= 0 ? Math.sign(d) * gap * Math.max(0, 1 - Math.abs(d) / 150) : 0;
      card.style.transform = `rotateY(${base + spread}deg) translateZ(${radius}px) rotateY(${FACE_ANGLE}deg)`;
    }
  }

  function setRot(value, animate) {
    rot = value;
    ring.classList.toggle("is-snapping", !!animate);
    ring.style.setProperty("--rot", `${rot}deg`);
  }

  // 회전각 → 가장 가까운 기록 번호
  const nearestIndex = (r) => Math.min(entries.length - 1, Math.max(0, Math.round(-r / step)));

  // 특정 기록을 앞으로
  function goTo(index, animate = true) {
    if (!entries.length) return;
    index = Math.min(entries.length - 1, Math.max(0, index));
    setRot(-index * step, animate);
    setActive(index);
  }

  function setActive(index) {
    if (index === active) return;
    active = index;
    layout();
    updateCaption();
  }

  function updateCaption() {
    const entry = entries[active];
    $("cap-date").textContent = entry ? longDate(entry.base_dt) : "";
    $("cap-title").textContent = entry ? entry.title || "제목 없음" : "";
    $("open-btn").disabled = !entry;
    $("prev-btn").disabled = !entry || active === 0;
    $("next-btn").disabled = !entry || active === entries.length - 1;
    scrub.value = Math.max(active, 0);
    if (entry) history.replaceState(null, "", `?date=${entry.base_dt}`);
  }

  // ============================================================
  // 드래그 (관성 포함)
  // ============================================================
  let drag = null;       // { x, rot, lastX, lastT, v }
  let inertia = 0;       // requestAnimationFrame id

  stage.addEventListener("pointerdown", (e) => {
    if (!entries.length || e.button !== 0) return;
    cancelAnimationFrame(inertia);
    drag = { x: e.clientX, rot, lastX: e.clientX, lastT: performance.now(), v: 0, moved: false, target: e.target };
    stage.setPointerCapture(e.pointerId);
  });

  stage.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (Math.abs(dx) > 4 && !drag.moved) {
      drag.moved = true;
      stage.classList.add("is-dragging");
    }
    if (!drag.moved) return;
    const now = performance.now();
    drag.v = (e.clientX - drag.lastX) / Math.max(1, now - drag.lastT);   // px/ms
    drag.lastX = e.clientX;
    drag.lastT = now;
    setRot(clampRot(drag.rot + (dx / PX_PER_CARD) * step), false);
    setActive(nearestIndex(rot));
  });

  const endDrag = (e) => {
    if (!drag) return;
    const { moved, v, target } = drag;
    drag = null;
    stage.classList.remove("is-dragging");
    if (!moved) return onCardClick(target);    // 거의 안 움직였으면 클릭으로 처리
    coast(v * 16);                              // px/frame 으로 바꿔 관성 시작
  };
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);

  // 놓은 뒤 속도를 줄이며 조금 더 돌다가 가장 가까운 카드에 멈춘다
  function coast(vPx) {
    const frame = () => {
      vPx *= 0.93;
      if (Math.abs(vPx) < 0.6) return goTo(nearestIndex(rot));
      setRot(clampRot(rot + (vPx / PX_PER_CARD) * step), false);
      setActive(nearestIndex(rot));
      inertia = requestAnimationFrame(frame);
    };
    inertia = requestAnimationFrame(frame);
  }

  // 첫 기록 앞·마지막 기록 뒤로 반 장 이상 넘어가지 않게
  const clampRot = (r) => Math.min(step * 0.5, Math.max(-(entries.length - 0.5) * step, r));

  function onCardClick(target) {
    const card = target.closest && target.closest(".card.is-entry");
    if (!card) return;
    const index = +card.dataset.index;
    if (index === active) openReader(entries[index].base_dt);
    else goTo(index);
  }

  // ── 휠: 여러 번 굴린 양을 모아 카드 단위로 넘긴다 ──
  let wheelAcc = 0;
  stage.addEventListener("wheel", (e) => {
    if (!entries.length) return;
    e.preventDefault();
    wheelAcc += Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    const cardsToMove = Math.trunc(wheelAcc / 60);
    if (cardsToMove) {
      wheelAcc -= cardsToMove * 60;
      goTo(active + cardsToMove);
    }
  }, { passive: false });

  // ── 키보드 ──
  stage.addEventListener("keydown", (e) => {
    const moves = { ArrowRight: 1, ArrowLeft: -1, PageDown: 10, PageUp: -10 };
    if (e.key in moves && entries.length) { e.preventDefault(); goTo(active + moves[e.key]); }
    else if (e.key === "Home" && entries.length) { e.preventDefault(); goTo(0); }
    else if (e.key === "End" && entries.length) { e.preventDefault(); goTo(entries.length - 1); }
    else if (e.key === "Enter" && entries[active]) { e.preventDefault(); openReader(entries[active].base_dt); }
  });
  document.addEventListener("keydown", (e) => {
    if (document.querySelector("dialog[open]") || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      openEditor(null);
    } else if (e.key === "/") {                 // '/' → 검색
      e.preventDefault();
      openSearch();
    }
  });

  // ── 버튼·슬라이더 ──
  $("prev-btn").addEventListener("click", () => goTo(active - 1));
  $("next-btn").addEventListener("click", () => goTo(active + 1));
  $("open-btn").addEventListener("click", () => entries[active] && openReader(entries[active].base_dt));
  scrub.addEventListener("input", () => goTo(+scrub.value));
  $("new-btn").addEventListener("click", () => openEditor(null));
  $("empty-new").addEventListener("click", () => openEditor(null));
  yearSelect.addEventListener("change", () => loadYear(yearSelect.value));

  // 화면 크기가 바뀌면(모바일 회전 등) 카드 크기에 맞춰 다시 배치
  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { const a = active; build(); active = -1; goTo(Math.max(a, 0), false); }, 200);
  });

  // ============================================================
  // 목록 불러오기
  // ============================================================
  async function loadYear(year, focusDt, openAfter = false) {
    let data;
    try {
      data = await api(year ? `${config.apiUrl}?year=${year}` : config.apiUrl);
    } catch (e) {
      toast(`불러오지 못했습니다: ${e.message}`);
      return;
    }
    currentYear = data.year;
    entries = data.entries;
    renderYears(data.years, data.year);
    active = -1;
    build();
    if (!entries.length) {
      setRot(0, false);
      updateCaption();
      return;
    }
    const idx = focusDt ? entries.findIndex((e) => e.base_dt === focusDt) : -1;
    // 처음 열 때는 맨 앞에서 시작해 최근 기록까지 돌아가는 연출
    setRot(0, false);
    requestAnimationFrame(() => goTo(idx >= 0 ? idx : entries.length - 1, true));
    if (openAfter && idx >= 0) openReader(focusDt);
  }

  function renderYears(years, selected) {
    yearSelect.replaceChildren();
    const list = years.some((y) => y.year === selected) ? years : [{ year: selected, count: 0 }, ...years];
    for (const y of list) {
      const opt = document.createElement("option");
      opt.value = y.year;
      opt.textContent = `${y.year}년 · ${y.count}`;
      opt.selected = y.year === selected;
      yearSelect.append(opt);
    }
  }

  // ============================================================
  // 읽기
  // ============================================================
  const reader = $("reader");

  async function openReader(dt) {
    let data;
    try {
      data = await api(entryUrl(dt));
    } catch (e) {
      toast(e.message);
      return;
    }
    reading = data;
    $("r-date").textContent = longDate(data.base_dt);
    $("r-title").textContent = data.title || "제목 없음";
    $("r-body").innerHTML = data.html;              // 서버에서 nh3 로 살균된 HTML
    $("r-updated").textContent = `마지막 수정 ${data.updated_at}`;
    renderSide(data);
    reader.showModal();
    if (data.photos.length) drawDayMap(data.photos);   // 창이 열려 크기가 정해진 뒤에 지도를 그린다
    const body = $("r-body");
    body.scrollTop = 0;
    body.focus({ preventScroll: true });   // 닫기 버튼 대신 본문에 초점 → 방향키·스페이스로 바로 스크롤
  }

  // ── 이날의 동선: 사진 줄 (순번·상태 테두리·설명 표시, 누르면 크게 보기) ──
  let dayMap = null;      // 읽기 창의 동선 지도 (창을 닫으면 지운다)

  function renderSide(data) {
    const photos = data.photos;
    const has = photos.length > 0;
    $("r-side").hidden = !has;
    reader.classList.toggle("has-side", has);
    $("r-maplink").href = TPDay.mapUrl(data.base_dt);
    const strip = $("r-photos");
    strip.replaceChildren();
    photos.forEach((p, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `strip-item st-${p.status}${p.has_note ? " has-note" : ""}`;
      btn.setAttribute("role", "listitem");
      btn.title = `${i + 1}번째 · ${p.photo_at.slice(11)}${p.has_note ? " · 설명 있음" : ""}${p.lat === null ? " · 위치 없음" : ""}`;
      const img = document.createElement("img");
      img.src = p.mini_url || p.thumb_url;
      img.alt = `${i + 1}번째 사진`;
      img.loading = "lazy";
      const seq = document.createElement("span");
      seq.className = "seq";
      seq.textContent = i + 1;
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = p.photo_at.slice(11);
      btn.append(img, seq, time);
      btn.addEventListener("click", () => openPhoto(photos, i));
      strip.append(btn);
    });
  }

  function drawDayMap(photos) {
    if (dayMap) dayMap.remove();
    dayMap = TPDay.dayMap($("r-map"), photos, { onSelect: (i) => openPhoto(photos, i) });
    $("r-map").hidden = !dayMap;
    $("r-nomap").hidden = !!dayMap;
  }

  // 사진 크게 보기 — 넘길 때마다 사진 줄과 지도 마커도 같이 강조
  function openPhoto(photos, index) {
    TPDay.lightbox(photos, index, {
      caption: (p, i) => `${i + 1} / ${photos.length} · ${p.photo_at}${p.lat === null ? " · 위치 없음" : ""}`,
      onChange: (i) => {
        $("r-photos").querySelectorAll(".strip-item").forEach((el, j) => el.classList.toggle("is-selected", j === i));
        if (dayMap) dayMap.select(i);
      },
    });
  }

  reader.addEventListener("close", () => {
    if (dayMap) { dayMap.remove(); dayMap = null; }
  });

  $("r-edit").addEventListener("click", () => {
    const data = reading;
    reader.close();
    openEditor(data);
  });

  $("r-delete").addEventListener("click", async () => {
    if (!reading || !confirm(`${longDate(reading.base_dt)} 기록을 삭제할까요?`)) return;
    try {
      await api(entryUrl(reading.base_dt), { method: "DELETE" });
    } catch (e) {
      toast(e.message);
      return;
    }
    const idx = entries.findIndex((e) => e.base_dt === reading.base_dt);
    const neighbor = entries[idx + 1] || entries[idx - 1];
    reader.close();
    toast("삭제했습니다.");
    loadYear(currentYear, neighbor && neighbor.base_dt);
  });

  // ============================================================
  // 쓰기 / 고치기
  // - 날짜는 오늘이 기본이고 언제든 바꿀 수 있다.
  // - 새 기록(create): 고른 날짜에 이미 기록이 있으면 알려 주고 [불러오기]로 그 기록을 고치게 한다.
  // - 고치기(update): 날짜를 바꾸면 저장할 때 기록이 그 날짜로 옮겨진다.
  // - 어느 경우든 대상 날짜에 다른 기록이 있으면 서버가 409 로 막는다 (덮어쓰기 방지).
  // ============================================================
  const editor = $("editor");
  const eDate = $("e-date"), eTitle = $("e-title"), eNote = $("e-note");
  const notice = $("e-notice");
  let editing = null;     // 고치는 중인 기록의 원래 날짜(base_dt), 새 기록이면 null
  let savedSnapshot = ""; // 마지막으로 불러온/저장한 내용 — 바뀌었는지 확인용
  let checkSeq = 0;       // 날짜 확인 요청 순서 (늦게 온 응답 무시)

  const snapshot = () => JSON.stringify([eDate.value, eTitle.value, eNote.value]);
  const isDirty = () => snapshot() !== savedSnapshot;
  const shortDate = (dt) => `${dt.slice(0, 4)}.${dt.slice(4, 6)}.${dt.slice(6, 8)}`;

  // dt: 새 기록의 날짜 (없으면 오늘) — 지도 화면의 '이날 일기 쓰기'에서 넘어올 때 쓴다
  function openEditor(data, dt) {
    fillEditor(data, data ? data.base_dt : dt || todayDt());
    $("e-error").hidden = true;
    showTab("write");
    editor.showModal();
    if (!data) checkDate();                   // 오늘 기록이 이미 있는지 확인
    eNote.focus();
  }

  // 편집기에 기록 채우기 (data 가 없으면 빈 새 기록)
  function fillEditor(data, dt) {
    editing = data ? data.base_dt : null;
    $("e-heading").textContent = data ? "기록 고치기" : "새 기록";
    eDate.value = toInput(dt);
    eTitle.value = data ? data.title : "";
    eNote.value = data ? data.note : "";
    setNotice("");
    savedSnapshot = snapshot();
    updateCount();
  }

  // 안내 문구 (+ 선택 버튼)
  function setNotice(text, buttonLabel, onClick) {
    notice.replaceChildren();
    notice.hidden = !text;
    if (!text) return;
    notice.append(document.createTextNode(text + " "));
    if (buttonLabel) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "inline-btn";
      btn.textContent = buttonLabel;
      btn.addEventListener("click", onClick);
      notice.append(btn);
    }
  }

  // 날짜를 바꿨을 때: 그날 기록이 있는지 확인해 안내한다
  async function checkDate() {
    const seq = ++checkSeq;
    setNotice("");
    if (!eDate.value) return;
    const dt = fromInput(eDate.value);
    if (editing && dt === editing) return;    // 원래 날짜로 되돌림
    let existing = null;
    try {
      existing = await api(entryUrl(dt));
    } catch (e) {
      if (e.status !== 404) { toast(e.message); return; }  // 404 = 그날 기록 없음
    }
    if (seq !== checkSeq) return;             // 그사이 날짜를 또 바꿨으면 무시

    if (editing) {
      if (existing) setNotice(`${shortDate(dt)}에는 이미 기록이 있어 이 날짜로 옮길 수 없습니다.`);
      else setNotice(`저장하면 이 기록이 ${shortDate(editing)} → ${shortDate(dt)}(으)로 옮겨집니다.`);
    } else if (existing) {
      setNotice(`${shortDate(dt)}에는 이미 기록이 있습니다. 하루에 한 건씩 기록됩니다.`, "그 기록 불러오기", () => {
        if (isDirty() && eNote.value.trim() && !confirm("작성 중인 내용 대신 그날 기록을 불러올까요?")) return;
        fillEditor(existing, existing.base_dt);
      });
    }
  }
  eDate.addEventListener("change", checkDate);

  function updateCount() {
    $("e-count").textContent = `${eNote.value.length.toLocaleString()}자`;
  }
  eNote.addEventListener("input", updateCount);

  // 탭: 쓰기 / 미리보기 (미리보기는 서버에서 저장과 같은 방식으로 변환·살균)
  function showTab(which) {
    const preview = which === "preview";
    $("tab-write").classList.toggle("is-on", !preview);
    $("tab-preview").classList.toggle("is-on", preview);
    $("tab-write").setAttribute("aria-selected", String(!preview));
    $("tab-preview").setAttribute("aria-selected", String(preview));
    eNote.hidden = preview;
    $("e-preview").hidden = !preview;
  }
  $("tab-write").addEventListener("click", () => { showTab("write"); eNote.focus(); });
  $("tab-preview").addEventListener("click", async () => {
    showTab("preview");
    $("e-preview").textContent = "변환 중…";
    try {
      const data = await api(config.previewUrl, { method: "POST", body: JSON.stringify({ note: eNote.value }) });
      $("e-preview").innerHTML = data.html || '<p class="muted">내용이 없습니다.</p>';
    } catch (e) {
      $("e-preview").textContent = e.message;
    }
  });

  async function save() {
    const errorBox = $("e-error");
    errorBox.hidden = true;
    const fail = (msg) => { errorBox.textContent = msg; errorBox.hidden = false; };
    if (!eDate.value) return fail("날짜를 고르세요.");
    if (!eNote.value.trim()) { showTab("write"); return fail("내용을 입력하세요."); }

    const dt = fromInput(eDate.value);
    const body = editing
      ? { mode: "update", title: eTitle.value, note: eNote.value, date: dt !== editing ? dt : undefined }
      : { mode: "create", title: eTitle.value, note: eNote.value };
    const btn = $("e-save");
    btn.disabled = true;
    let result;
    try {
      result = await api(entryUrl(editing || dt), { method: "PUT", body: JSON.stringify(body) });
    } catch (e) {
      if (e.status === 409 && !editing) {
        return fail(`${shortDate(dt)}에는 이미 기록이 있습니다. 날짜를 바꾸거나, 위의 [그 기록 불러오기]로 고쳐 주세요.`);
      }
      return fail(e.message);
    } finally {
      btn.disabled = false;
    }
    const moved = editing && result.base_dt !== editing;
    savedSnapshot = snapshot();
    editor.close();
    toast(moved ? `${shortDate(result.base_dt)}(으)로 옮겨 저장했습니다.` : "저장했습니다.");
    loadYear(result.base_dt.slice(0, 4), result.base_dt);
  }
  $("e-form").addEventListener("submit", (e) => { e.preventDefault(); save(); });
  editor.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
  });

  // 닫기: 고친 내용이 있으면 확인
  function closeEditor() {
    if (isDirty() && !confirm("저장하지 않은 내용이 있습니다. 닫을까요?")) return;
    editor.close();
  }
  editor.addEventListener("cancel", (e) => { e.preventDefault(); closeEditor(); });  // Esc
  window.addEventListener("beforeunload", (e) => { if (editor.open && isDirty()) e.preventDefault(); });

  // ============================================================
  // 검색 — 일기·사진 설명의 제목/본문 (/api/search)
  // - 일기 결과를 누르면 그해 링에서 그날로 돌아가 읽기 창을 연다.
  // - 사진 설명 결과는 그날 여행기로 간다.
  // - 입력을 멈추고 0.3초 뒤 자동으로 찾는다 (Enter 는 바로).
  // ============================================================
  const searchDlg = $("search"), sInput = $("s-input"), sResults = $("s-results");
  let searchSeq = 0, searchTimer = 0, lastQuery = "";

  function openSearch() {
    searchDlg.showModal();
    sInput.focus();
    sInput.select();
  }

  async function runSearch() {
    clearTimeout(searchTimer);
    const q = sInput.value.trim();
    if (q === lastQuery) return;
    lastQuery = q;
    const seq = ++searchSeq;
    if (!q) {
      sResults.replaceChildren(textP("제목과 본문에서 찾습니다. 대소문자는 구분하지 않습니다."));
      return;
    }
    sResults.replaceChildren(textP("찾는 중…"));
    let data;
    try {
      data = await api(`${config.searchUrl}?q=${encodeURIComponent(q)}`);
    } catch (e) {
      if (seq === searchSeq) sResults.replaceChildren(textP(e.message));
      return;
    }
    if (seq !== searchSeq) return;               // 그사이 다른 검색어로 다시 찾았으면 버림
    renderResults(data);
  }

  function textP(text) {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = text;
    return p;
  }

  // 검색어를 <mark> 로 강조 (textContent 로만 넣어 HTML 이 섞이지 않게)
  function highlight(el, text, keyword) {
    const lower = text.toLowerCase(), k = keyword.toLowerCase();
    let i = 0;
    while (k) {
      const at = lower.indexOf(k, i);
      if (at < 0) break;
      el.append(text.slice(i, at));
      const m = document.createElement("mark");
      m.textContent = text.slice(at, at + k.length);
      el.append(m);
      i = at + k.length;
    }
    el.append(text.slice(i));
    return el;
  }

  function resultItem(tag, meta, title, snippet, keyword, img) {
    const item = document.createElement(tag);
    item.className = "s-item";
    if (img) {
      const im = document.createElement("img");
      im.src = img;
      im.alt = "";
      im.loading = "lazy";
      item.append(im);
    }
    const box = document.createElement("span");
    box.className = "s-text";
    const m = document.createElement("span");
    m.className = "s-meta";
    m.textContent = meta;
    box.append(m);
    if (title) {
      const t = document.createElement("span");
      t.className = "s-title";
      box.append(highlight(t, title, keyword));
    }
    const sn = document.createElement("span");
    sn.className = "s-snip";
    box.append(highlight(sn, snippet, keyword));
    item.append(box);
    return item;
  }

  function renderResults(data) {
    sResults.replaceChildren();
    const k = data.q;
    if (!data.diaries.length && !data.notes.length) {
      sResults.append(textP(`'${k}'(이)가 들어간 기록이 없습니다.`));
      return;
    }
    const section = (title, items) => {
      const h = document.createElement("h3");
      h.textContent = title;
      const ul = document.createElement("ul");
      ul.className = "s-list";
      for (const it of items) { const li = document.createElement("li"); li.append(it); ul.append(li); }
      sResults.append(h, ul);
    };
    const more = (n) => (n >= data.limit ? ` (최근 ${data.limit}건까지)` : "");
    if (data.diaries.length) {
      section(`일기 ${data.diaries.length}편${more(data.diaries.length)}`, data.diaries.map((d) => {
        const btn = resultItem("button", longDate(d.base_dt), d.title || "제목 없음", d.snippet, k);
        btn.type = "button";
        btn.addEventListener("click", () => {
          searchDlg.close();
          loadYear(d.base_dt.slice(0, 4), d.base_dt, true);   // 그날로 링을 돌리고 읽기 창 열기
        });
        return btn;
      }));
    }
    if (data.notes.length) {
      section(`사진 설명 ${data.notes.length}건${more(data.notes.length)}`, data.notes.map((n) => {
        const a = resultItem("a", `${n.photo_at} · 사진 설명`, n.title, n.snippet, k, n.mini_url);
        a.href = `${config.storyPage}?start=${n.base_dt}&end=${n.base_dt}`;   // 그날 여행기에서 사진과 설명 보기
        return a;
      }));
    }
  }

  $("search-btn").addEventListener("click", openSearch);
  $("s-form").addEventListener("submit", (e) => { e.preventDefault(); lastQuery = null; runSearch(); });
  sInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 300);
  });

  // 공통: [data-close] 버튼, 바깥(배경) 클릭으로 닫기
  for (const dlg of [reader, editor, searchDlg]) {
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg || e.target.closest("[data-close]")) {
        if (dlg === editor) closeEditor(); else dlg.close();
      }
    });
    dlg.addEventListener("close", () => stage.focus({ preventScroll: true }));
  }

  // ============================================================
  // 알림
  // ============================================================
  let toastTimer = 0;
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  // 그날 기록이 있으면 고치기로, 없으면 그 날짜의 새 기록으로 편집기를 연다
  async function writeFor(dt) {
    try {
      openEditor(await api(entryUrl(dt)));
    } catch (e) {
      if (e.status === 404) openEditor(null, dt);
      else toast(e.message);
    }
  }

  // ============================================================
  // 시작: 주소의 ?date= 가 있으면 그해·그날로, 없으면 최근 연도의 마지막 기록으로
  //       ?date=YYYYMMDD&open=1 이면 그날 기록을 바로 연다 (지도 등 다른 화면에서 연결할 때)
  //       ?date=YYYYMMDD&write=1 이면 그날 기록을 쓰기(없을 때)·고치기(있을 때)로 바로 연다
  // ============================================================
  const params = new URLSearchParams(location.search);
  const q = params.get("date");
  const startDt = /^\d{8}$/.test(q || "") ? q : null;
  const writeAfter = startDt && params.get("write") === "1";
  loadYear(startDt ? startDt.slice(0, 4) : null, startDt, !writeAfter && params.get("open") === "1");
  stage.focus({ preventScroll: true });
  if (writeAfter) writeFor(startDt);
})();

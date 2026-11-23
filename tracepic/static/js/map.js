// 지도 화면 스크립트 (Leaflet)
// - 조회 조건 = 기간(기본: 이번 달 1일 ~ 오늘) + 상태. 날짜 목록은 그 기간 안에서 사진이 있는 날을 일자별로 보여 준다.
// - 날짜를 누르면 그날 사진만 지도에 표시하고, '기간 전체'(또는 같은 날 다시 누르기)로 돌아간다.
// - /api/photo-dates 로 일자별 장수를, /api/map-photos 로 사진을 받는다.
// - 사진은 촬영 시각순으로 번호(1, 2, 3…)를 매겨 마커와 아래쪽 '촬영 순서 필름'에 함께 보여 준다.
//   필름(과 크게 보기의 이전/다음)은 **최근 사진부터** 나온다. 번호는 촬영 순서 그대로다(맨 앞이 가장 큰 번호).
//   위치 없는 사진은 지도에는 못 찍지만 필름에는 순서대로 나온다.
// - 메모리 절약 (사진이 수천 장이어도 휴대폰 탭이 버티게, 대신 아주 조금 늦게 뜰 수 있음):
//   · 필름은 화면 근처 칸만 만들고 나머지는 빈 여백으로 둔다(renderFilmWindow). 지나간 칸은 지워서 사진도 메모리에서 빠진다.
//   · 마커 그림(DOM)은 지도에 나타날 때 만든다(PhotoIcon). 묶음 안·화면 밖 마커는 그림이 없다.
//   · 지도 타일은 화면 밖 여분을 적게 들고, 움직임이 멈춘 뒤 받는다.
//   · 이미지 주소는 서버가 보내지 않고 pic_id 로 만든다. 설명 편집기(OverType)는 '쓰기'를 처음 누를 때 불러온다.
// - '이동 경로'를 켜면 촬영 시각순으로 선을 잇는다.
// - 필름은 Tab 으로 한 번만 들어가고(선택된 사진), 그 안에서는 ← → (Home/End)로 옮겨 다니며 Enter 로 크게 본다.
// - 사진 크게 보기 창에서 이전/다음(촬영순), 상태 변경, 위치 찍기·수정, 설명(마크다운) 쓰기를 한다.
// - 날짜 목록의 📖 = 일기가 있는 날. 날짜를 고르면 패널에 그날 일기 요약이 나오고, 펼쳐 읽거나 일기 화면에서 쓸 수 있다.
// - '여행기' 버튼은 지금 기간·상태로 /story(날짜별 일기 + 동선 + 사진 설명)를 연다.
// - 선택한 기간·날짜·상태는 주소(?start=&end=&day=&status=)에 남겨 새로고침해도 유지한다.
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("map-config").textContent);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const $ = (id) => document.getElementById(id);
  const startInput = $("start");
  const endInput = $("end");
  const routeToggle = $("route-toggle");
  const summary = $("map-summary");
  const dateList = $("date-list");
  const film = $("film");
  const statusInputs = [...document.querySelectorAll('input[name="status"]')];
  const STATUS_LABEL = Object.fromEntries(config.statuses);   // { C: "나만 보기", ... }

  // 타일 설정: 화면 밖 여분 타일을 1줄만 들고(기본 2), 지도를 끌거나 확대하는 중에는 받지 않고 멈춘 뒤 받는다
  // → 들고 있는 타일 이미지가 줄어든다 (움직인 직후 잠깐 빈 칸이 보일 수 있음)
  const TILE_OPTS = {
    maxZoom: 19,
    keepBuffer: 1,
    updateWhenIdle: true,
    updateWhenZooming: false,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  };

  // ── 지도 기본 설정 (사진이 없으면 한반도 중심) ──
  const map = L.map("map", { zoomControl: true }).setView([36.5, 127.8], 7);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    ...TILE_OPTS,
  }).addTo(map);

  // 패널 내용(날짜 목록 등)이 채워지면 지도 영역 크기가 바뀐다 → Leaflet 에 다시 알려 줘야 타일·중심이 맞는다
  new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById("map"));

  // chunkedLoading: 마커 수천 개를 조금씩 나눠 넣어 화면이 멈추지 않게 한다
  // removeOutsideVisibleBounds: 화면 밖 마커는 지도에서 빼 둔다(그림 DOM 도 없어짐 — 기본값이지만 명시)
  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 50, chunkedLoading: true, removeOutsideVisibleBounds: true,
  });
  map.addLayer(cluster);
  // 마커마다 클릭 함수를 따로 두지 않고 묶음에서 한 번에 받는다 (이어서 ← → 로 넘길 수 있게 필름에 포커스)
  cluster.on("click", (e) => {
    const p = e.layer.options.photo;
    if (p) { highlight(p.pic_id); focusFilm(p.pic_id); }
  });

  // ── 상태 ──
  let routeLine = null;
  let dates = [];             // 조회 기간 안에서 사진이 있는 날 [{ base_dt, count }] 날짜 오름차순
  let diaries = new Map();    // 조회 기간 안의 일기 base_dt → { title, excerpt }
  let photos = [];            // 조회된 사진 (화면 순서 = 최근 것부터, p.seq = 촬영순 번호 1부터)
  const indexById = new Map(); // pic_id → photos 위치 (사진마다 배열을 훑지 않게)
  const markers = new Map();  // pic_id → Leaflet 마커 (위치 있는 사진만)
  let range = null;           // 조회 기간 { start, end } — 날짜 목록이 이 기간의 일자별로 나온다
  let focusDay = null;        // 날짜 목록에서 고른 하루 (null 이면 기간 전체를 지도에 표시)
  let selectedId = null;      // 강조 중인 사진
  let requestSeq = 0;         // 늦게 도착한 이전 요청 응답을 무시하기 위한 번호

  // ── 날짜 형식 변환 ──
  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const toInput = (dt) => `${dt.slice(0, 4)}-${dt.slice(4, 6)}-${dt.slice(6, 8)}`; // 20261117 → 2026-11-17
  const fromInput = (v) => v.replaceAll("-", "");                                  // 2026-11-17 → 20261117
  function label(dt) {
    const d = new Date(+dt.slice(0, 4), +dt.slice(4, 6) - 1, +dt.slice(6, 8));
    return `${dt.slice(0, 4)}.${dt.slice(4, 6)}.${dt.slice(6, 8)} (${WEEKDAYS[d.getDay()]})`;
  }
  const shortLabel = (dt) => `${+dt.slice(4, 6)}월 ${+dt.slice(6, 8)}일`;
  // 기본 조회 기간: 이번 달 1일 ~ 오늘 (브라우저의 현지 날짜 기준)
  function defaultRange() {
    const now = new Date();
    const ymd = (d) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
    return { start: ymd(new Date(now.getFullYear(), now.getMonth(), 1)), end: ymd(now) };
  }

  // ============================================================
  // 서버 통신 (로그인 만료면 로그인 화면으로, 쓰기 요청은 CSRF 헤더)
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
    if (!res.ok) throw new Error(data.error || `요청 실패 (HTTP ${res.status})`);
    return data;
  }
  const photoUrl = (id) => config.photoUrl0.replace(/0$/, String(id));   // /api/photos/0 → /api/photos/123
  // 이미지 주소: /photos/0/mini → /photos/123/mini (지도 목록은 주소 없이 pic_id 만 온다)
  const imgUrl = (tpl, id) => tpl.replace("/0/", `/${id}/`);
  const miniUrl = (p) => imgUrl(config.miniUrl0, p.pic_id);
  const thumbUrl = (p) => imgUrl(config.thumbUrl0, p.pic_id);
  const imageUrl = (p) => imgUrl(config.imageUrl0, p.pic_id);

  // ============================================================
  // 상태 조건
  // ============================================================
  const statusFilter = () => statusInputs.filter((i) => i.checked).map((i) => i.value);
  function setStatusFilter(list) {
    for (const i of statusInputs) i.checked = list.includes(i.value);
  }
  const isDefaultFilter = () =>
    statusFilter().slice().sort().join() === config.defaultStatuses.slice().sort().join();

  function updateUrl() {
    const q = new URLSearchParams();
    if (range) { q.set("start", range.start); q.set("end", range.end); }
    if (focusDay) q.set("day", focusDay);
    if (!isDefaultFilter()) q.set("status", statusFilter().join(","));
    history.replaceState(null, "", q.toString() ? `?${q}` : location.pathname);
    // 여행기 링크도 같은 기간·상태로 (고른 날이 있으면 그날만)
    const sq = new URLSearchParams();
    if (range) {
      sq.set("start", focusDay || range.start);
      sq.set("end", focusDay || range.end);
    }
    if (!isDefaultFilter() && statusFilter().length) sq.set("status", statusFilter().join(","));
    $("story-link").href = `${config.storyPage}?${sq}`;
  }

  // ============================================================
  // 날짜 목록 (조회 기간 안의 일자별)
  // ============================================================
  async function loadDates() {
    const q = `status=${statusFilter().join(",")}&start=${range.start}&end=${range.end}`;
    const data = await api(`${config.datesUrl}?${q}`);
    dates = data.dates.reverse();   // 날짜 오름차순 (필름 순서와 같게)
    diaries = new Map((data.diaries || []).map((d) => [d.base_dt, d]));
    renderDates();
  }

  function renderDates() {
    dateList.replaceChildren();
    if (dates.length === 0) return;
    // 맨 위: 기간 전체 (누르면 날짜 선택 해제)
    const total = dates.reduce((n, d) => n + d.count, 0);
    dateList.append(dateItem("", "기간 전체", `${total}장`, () => { focusDay = null; showPhotos(); }));
    for (const d of dates) {
      // 같은 날을 다시 누르면 기간 전체로 돌아간다
      dateList.append(dateItem(d.base_dt, label(d.base_dt), `${d.count}장`,
        () => { focusDay = focusDay === d.base_dt ? null : d.base_dt; showPhotos(); }));
    }
    markActiveDate();
  }

  function dateItem(dt, text, countText, onClick) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = dt ? "date-item" : "date-item date-all";
    btn.dataset.dt = dt;
    const name = document.createElement("span");
    name.textContent = text;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = countText;
    btn.append(name);
    if (dt && diaries.has(dt)) {             // 일기가 있는 날
      const mark = document.createElement("span");
      mark.className = "dd-mark";
      mark.textContent = "📖";
      mark.title = "일기 있음";
      mark.setAttribute("aria-label", "일기 있음");
      btn.append(mark);
    }
    btn.append(count);
    btn.addEventListener("click", onClick);
    li.append(btn);
    return li;
  }

  function markActiveDate() {
    for (const btn of dateList.querySelectorAll(".date-item")) {
      btn.classList.toggle("is-active", btn.dataset.dt === (focusDay || ""));
    }
    renderDayDiary();
  }

  // ============================================================
  // 고른 날의 일기 (패널 요약 → 펼치기 / 일기 화면에서 쓰기·고치기)
  // ============================================================
  const diaryWriteUrl = (dt) => `${config.diaryPage}?date=${dt}&write=1`;

  function renderDayDiary() {
    const box = $("day-diary");
    box.hidden = !focusDay;
    if (!focusDay) return;
    const d = diaries.get(focusDay);
    $("dd-title").textContent = d ? d.title || "제목 없음" : "";
    $("dd-title").hidden = !d;
    $("dd-excerpt").textContent = d ? d.excerpt : "이날 일기가 아직 없습니다.";
    $("dd-open").hidden = !d;
    $("dd-write").textContent = d ? "고치기" : "이날 일기 쓰기";
    $("dd-write").href = diaryWriteUrl(focusDay);
  }

  const diaryView = $("diary-view");
  async function openDiary(dt) {
    let d;
    try {
      d = await api(`${config.diaryApi}/${dt}`);
    } catch (e) {
      summary.textContent = `일기를 불러오지 못했습니다: ${e.message}`;
      return;
    }
    $("dv-date").textContent = label(dt);
    $("dv-title").textContent = d.title || "제목 없음";
    $("dv-body").innerHTML = d.html;              // 서버에서 nh3 로 살균한 HTML
    $("dv-updated").textContent = `${d.updated_at} 저장`;
    $("dv-edit").href = diaryWriteUrl(dt);
    $("dv-story").href = `${config.storyPage}?start=${dt}&end=${dt}`;
    diaryView.showModal();
    $("dv-body").scrollTop = 0;
  }
  $("dd-open").addEventListener("click", () => focusDay && openDiary(focusDay));
  diaryView.addEventListener("click", (e) => {
    if (e.target === diaryView || e.target.closest("[data-close]")) diaryView.close();
  });

  // ============================================================
  // 조회: 기간 → 날짜 목록(일자별) → 지도·필름
  // ============================================================
  async function search(start, end, { keepView = false, day = null } = {}) {
    if (start > end) [start, end] = [end, start];
    range = { start, end };
    startInput.value = toInput(start);
    endInput.value = toInput(end);
    focusDay = day;
    if (statusFilter().length === 0) {
      ++requestSeq;
      dates = [];
      renderDates();
      draw([], true);
      updateUrl();
      summary.textContent = "상태를 하나 이상 골라 주세요.";
      return;
    }
    const seq = ++requestSeq;
    summary.textContent = "불러오는 중…";
    try {
      await loadDates();
    } catch (e) {
      if (seq === requestSeq) summary.textContent = `불러오지 못했습니다: ${e.message}`;
      return;
    }
    if (seq !== requestSeq) return;
    if (focusDay && !dates.some((d) => d.base_dt === focusDay)) focusDay = null;   // 고른 날에 사진이 없어졌으면 해제
    markActiveDate();
    if (dates.length === 0) {
      updateUrl();
      draw([], true);
      summary.textContent = "이 기간에는 사진이 없습니다. '전체'로 모든 기간을 볼 수 있습니다.";
      return;
    }
    await showPhotos(keepView);
  }

  // 지도·필름 표시: 고른 날이 있으면 그날만, 없으면 조회 기간 전체
  async function showPhotos(keepView = false) {
    markActiveDate();
    updateUrl();
    const [start, end] = focusDay ? [focusDay, focusDay] : [range.start, range.end];
    const seq = ++requestSeq;
    summary.textContent = "불러오는 중…";
    let data;
    try {
      data = await api(`${config.photosUrl}?start=${start}&end=${end}&status=${statusFilter().join(",")}`);
    } catch (e) {
      if (seq === requestSeq) summary.textContent = `불러오지 못했습니다: ${e.message}`;
      return;
    }
    if (seq !== requestSeq) return; // 그사이 다른 조건으로 다시 불렀으면 버림
    draw(newestFirst(data.photos), keepView);
    renderSummary();
  }

  // 조회 결과 요약 (위치를 찍거나 지우면 다시 부른다)
  function renderSummary() {
    if (photos.length === 0) {
      summary.textContent = "조건에 맞는 사진이 없습니다";
      return;
    }
    const unlocated = photos.filter((p) => p.lat === null).length;
    const parts = [`${focusDay ? shortLabel(focusDay) + " " : ""}사진 ${photos.length}장`];
    if (unlocated) parts.push(`위치 없음 ${unlocated}장`);
    summary.textContent = parts.join(" · ");
  }

  // 서버는 촬영 시각순으로 준다 → 번호는 그 순서대로 매기고, 화면에는 최근 것부터 보여 준다
  function newestFirst(list) {
    list.forEach((p, i) => { p.seq = i + 1; });
    return list.reverse();
  }

  // list: 화면 순서(최근 것부터), p.seq 가 매겨진 목록
  function draw(list, keepView) {
    photos = list;
    indexById.clear();
    photos.forEach((p, i) => indexById.set(p.pic_id, i));
    cluster.clearLayers();
    markers.clear();
    if (routeLine) routeLine.remove();
    routeLine = null;
    renderFilm(keepView);

    const located = photos.filter((p) => p.lat !== null);
    if (located.length === 0) return;
    for (const p of located) {
      const marker = L.marker([p.lat, p.lng], { icon: photoIcon(p), title: `${p.seq}. ${p.photo_at}`, photo: p });
      marker.bindPopup(() => popupContent(p), { minWidth: 200 });   // 팝업 내용은 열 때 만든다
      markers.set(p.pic_id, marker);
    }
    cluster.addLayers([...markers.values()]);

    // 이동 경로 (화면 순서는 최근 것부터지만 선은 같은 점들을 잇는 것이라 모양은 촬영순과 같다)
    const latlngs = located.map((p) => [p.lat, p.lng]);
    routeLine = L.polyline(latlngs, { color: getAccent(), weight: 3, opacity: 0.7, dashArray: "6 6" });
    if (routeToggle.checked) routeLine.addTo(map);

    if (!keepView) {
      // 아래쪽 필름에 가리지 않도록 그 높이만큼 아래 여백을 더 준다
      const filmH = film.hidden ? 0 : film.offsetHeight + 24;
      map.fitBounds(L.latLngBounds(latlngs), {
        paddingTopLeft: [40, 40], paddingBottomRight: [40, 40 + filmH], maxZoom: 16,
      });
    }
    if (selectedId !== null) highlight(selectedId);
  }

  // 상태·설명·선택 여부 → CSS 클래스 (안쪽 테두리 = 상태 색, 바깥 테두리 = 설명 있음)
  const photoClass = (base, p) =>
    `${base} st-${p.status}${p.has_note ? " has-note" : ""}${p.pic_id === selectedId ? " is-selected" : ""}`;

  // 썸네일 마커 아이콘: 사진 + 순번 배지, 테두리 색으로 상태·설명 표시
  // - L.divIcon 에 DOM 을 미리 넣으면 마커 수천 개의 그림이 처음부터 다 만들어진다.
  //   그래서 Leaflet 이 마커를 지도에 올릴 때(createIcon) 그 자리에서 만들고, 내려가면 버린다.
  // - 클래스(상태·설명·선택)도 그때의 값으로 정하므로 묶음에서 풀려 다시 나와도 모양이 맞다.
  const PhotoIcon = L.DivIcon.extend({
    createIcon(oldIcon) {
      const p = this.options.photo;
      this.options.className = photoClass("photo-marker", p);
      this.options.html = markerBox(p);
      const el = L.DivIcon.prototype.createIcon.call(this, oldIcon);
      this.options.html = "";            // 만든 DOM 은 지도에 붙은 것만 남긴다 (아이콘 객체에 들고 있지 않음)
      return el;
    },
  });
  const photoIcon = (p) => new PhotoIcon({ photo: p, iconSize: [48, 48], iconAnchor: [24, 24] });

  function markerBox(p) {
    const box = document.createElement("div");
    const img = document.createElement("img");
    img.src = miniUrl(p);
    img.alt = "";
    img.decoding = "async";
    const num = document.createElement("span");
    num.className = "seq";
    num.textContent = p.seq;
    box.append(img, num);
    return box;
  }

  // 마커를 눌렀을 때 팝업 (DOM 으로 만들어 파일명에 HTML 이 있어도 안전)
  function popupContent(p) {
    const box = document.createElement("div");
    box.className = "photo-popup";
    const img = document.createElement("img");
    img.src = thumbUrl(p);
    img.alt = p.name;
    img.addEventListener("click", () => openViewer(indexById.get(p.pic_id)));
    const time = document.createElement("div");
    time.className = "time";
    time.textContent = `${p.seq}번째 · ${p.photo_at}`;
    const meta = document.createElement("div");
    meta.className = "name muted small";
    meta.textContent = `${STATUS_LABEL[p.status] || p.status}${p.has_note ? " · 설명 있음" : ""}${p.name ? " · " + p.name : ""}`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-link";
    btn.textContent = "크게 보기 · 설명";
    btn.addEventListener("click", () => openViewer(indexById.get(p.pic_id)));
    box.append(img, time, meta, btn);
    return box;
  }

  // ── 촬영 순서 필름 (최근 사진부터) ──
  // 사진이 수천 장이면 버튼·사진을 다 만들면 휴대폰 메모리가 모자란다.
  // 그래서 칸 폭을 CSS 변수(--film-item-w, --film-day-w)로 고정해 두고, 각 칸의 위치만 계산해 둔 뒤
  // 지금 보이는 곳 앞뒤 한 화면씩만 실제 버튼으로 만든다. 나머지는 양 끝 빈 여백(.film-pad)이 폭만 차지한다.
  let slots = [];                 // 필름 칸: { day: base_dt } (날짜 구분) 또는 { p } (사진)
  let slotX = [];                 // 칸마다 왼쪽 위치(px), 마지막 원소는 전체 폭
  const slotOf = new Map();       // pic_id → slots 위치
  const filmNodes = new Map();    // pic_id → 지금 만들어 둔 버튼 (화면 근처만)
  let filmRange = [0, 0];         // 지금 만든 칸 범위 [from, to)
  const padL = document.createElement("div");
  const padR = document.createElement("div");
  padL.className = padR.className = "film-pad";
  padL.setAttribute("aria-hidden", "true");
  padR.setAttribute("aria-hidden", "true");

  // keepScroll: 같은 목록을 다시 그릴 때(위치 저장 등) 필름 스크롤 위치를 그대로 둔다
  function renderFilm(keepScroll = false) {
    const scroll = keepScroll ? film.scrollLeft : 0;
    film.hidden = photos.length === 0;
    slots = [];
    slotOf.clear();
    let prevDt = null;
    for (const p of photos) {
      if (p.base_dt !== prevDt) {           // 날짜가 바뀌는 곳에 구분 칸
        slots.push({ day: p.base_dt });
        prevDt = p.base_dt;
      }
      slotOf.set(p.pic_id, slots.length);
      slots.push({ p });
    }
    filmNodes.clear();
    film.replaceChildren(padL, padR);
    measureFilm();
    padR.style.width = `${slotX[slots.length]}px`;   // 전체 폭을 먼저 잡아야 스크롤 위치를 되돌릴 수 있다
    film.scrollLeft = scroll;
    renderFilmWindow(true);
  }

  // 칸 위치 계산 (화면 폭이 바뀌어 칸 폭이 달라지면 다시)
  function measureFilm() {
    const cs = getComputedStyle(film);
    const itemW = parseFloat(cs.getPropertyValue("--film-item-w")) || 70;
    const dayW = parseFloat(cs.getPropertyValue("--film-day-w")) || 24;
    slotX = new Array(slots.length + 1);
    let x = 0;
    slots.forEach((sl, i) => { slotX[i] = x; x += sl.p ? itemW : dayW; });
    slotX[slots.length] = x;
  }

  // x 위치에 있는 칸 번호 (이진 탐색)
  function slotAt(x) {
    let lo = 0, hi = slots.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (slotX[mid] <= x) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  // 보이는 곳 앞뒤 한 화면씩만 버튼으로 만든다. 범위 밖으로 나간 버튼은 버린다(사진 메모리도 함께 풀림)
  function renderFilmWindow(force = false) {
    if (slots.length === 0 || film.hidden) return;
    const w = film.clientWidth || window.innerWidth;
    const from = slotAt(Math.max(0, film.scrollLeft - w));
    const to = Math.min(slots.length, slotAt(film.scrollLeft + 2 * w) + 1);
    if (!force && from === filmRange[0] && to === filmRange[1]) return;
    // 포커스 중인 버튼은 다시 붙일 때 포커스가 풀리므로 기억했다가 돌려준다
    const focusedId = film.contains(document.activeElement) ? Number(document.activeElement.dataset.id) : null;
    const nodes = [];
    const keep = new Map();
    for (let i = from; i < to; i++) {
      const sl = slots[i];
      if (sl.day) { nodes.push(dayNode(sl.day, i === 0)); continue; }
      const el = filmNodes.get(sl.p.pic_id) || filmButton(sl.p);
      keep.set(sl.p.pic_id, el);
      nodes.push(el);
    }
    filmNodes.clear();
    for (const [id, el] of keep) filmNodes.set(id, el);
    padL.style.width = `${slotX[from]}px`;
    padR.style.width = `${slotX[slots.length] - slotX[to]}px`;
    film.replaceChildren(padL, ...nodes, padR);
    filmRange = [from, to];
    syncTabStop();
    if (focusedId !== null) filmNodes.get(focusedId)?.focus({ preventScroll: true });
  }

  function dayNode(dt, first) {
    const day = document.createElement("div");
    day.className = first ? "film-day is-first" : "film-day";
    day.textContent = `${+dt.slice(4, 6)}.${+dt.slice(6, 8)}`;
    return day;
  }

  function filmButton(p) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = photoClass("film-item", p);
    btn.dataset.id = p.pic_id;
    btn.setAttribute("role", "listitem");
    btn.tabIndex = -1;                    // Tab 정지점은 하나만 (syncTabStop)
    btn.title = `${p.seq}번째 · ${p.photo_at} · ${STATUS_LABEL[p.status] || p.status}` +
      `${p.has_note ? " · 설명 있음" : ""}${p.lat === null ? " · 위치 없음" : ""}`;
    const img = document.createElement("img");
    img.src = miniUrl(p);
    img.alt = "";
    img.decoding = "async";
    const num = document.createElement("span");
    num.className = "seq";
    num.textContent = p.seq;
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = p.photo_at.slice(11);
    btn.append(img, num, time);
    if (p.lat === null) {
      const nl = document.createElement("span");
      nl.className = "noloc";
      nl.textContent = "위치 없음";
      btn.append(nl);
    }
    return btn;
  }

  // 스크롤하면 다음 프레임에 한 번만 다시 계산 (스크롤 중 매번 하지 않게)
  let filmTick = 0;
  film.addEventListener("scroll", () => {
    if (!filmTick) filmTick = requestAnimationFrame(() => { filmTick = 0; renderFilmWindow(); });
  }, { passive: true });
  // 화면 폭이 바뀌면(모바일 회전 등) 칸 폭이 달라질 수 있다
  new ResizeObserver(() => { if (slots.length) { measureFilm(); renderFilmWindow(true); } }).observe(film);

  // 버튼마다 함수를 두지 않고 필름에서 한 번에 받는다
  const photoOf = (el) => photos[indexById.get(Number(el.dataset.id))];
  film.addEventListener("click", (e) => {
    const el = e.target.closest(".film-item");
    if (el && photoOf(el)) selectPhoto(photoOf(el));
  });
  film.addEventListener("dblclick", (e) => {
    const el = e.target.closest(".film-item");
    if (el && photoOf(el)) openViewer(indexById.get(Number(el.dataset.id)));
  });

  // 그 사진 칸이 필름 가운데 오게 스크롤
  function scrollFilmTo(id, smooth) {
    const i = slotOf.get(id);
    if (i === undefined || film.hidden) return;
    const left = (slotX[i] + slotX[i + 1]) / 2 - film.clientWidth / 2;
    film.scrollTo({ left: Math.max(0, left), behavior: smooth ? "smooth" : "auto" });
  }

  // 필름의 Tab 정지점: 선택된 사진(안 만들어져 있으면 만든 것 중 첫 칸) 하나만 tabindex=0
  function syncTabStop() {
    const stop = filmNodes.get(selectedId) || filmNodes.values().next().value;
    for (const el of filmNodes.values()) el.tabIndex = el === stop ? 0 : -1;
  }

  const filmItem = (id) => filmNodes.get(id);
  // 포커스 옮기기: 아직 버튼이 없으면(멀리 있는 사진) 바로 그 자리로 스크롤해서 만든 뒤 옮긴다
  function focusFilm(id) {
    if (!filmNodes.has(id)) {
      scrollFilmTo(id, false);
      renderFilmWindow();
    }
    filmNodes.get(id)?.focus({ preventScroll: true });   // 스크롤은 highlight 가 부드럽게 한다
  }

  // 방향키로 옮기기: 위치 있는 사진은 지도를 그 마커로, 없는 사진은 강조만 (크게 보기는 Enter)
  function stepTo(index) {
    if (index < 0 || index >= photos.length) return;
    const p = photos[index];
    highlight(p.pic_id);
    focusFilm(p.pic_id);
    const marker = markers.get(p.pic_id);
    if (marker) cluster.zoomToShowLayer(marker, () => marker.openPopup());
    else map.closePopup();
  }

  // 지금 선택된 사진 위치 (없으면 -1)
  const selectedIndex = () => indexById.get(selectedId) ?? -1;

  // ← → 한 칸, Home/End 처음·끝, Enter 크게 보기 (Space 는 클릭과 같음)
  function filmKey(e, index) {
    const moves = { ArrowLeft: index - 1, ArrowUp: index - 1, ArrowRight: index + 1, ArrowDown: index + 1,
      Home: 0, End: photos.length - 1 };
    if (e.key === "Enter") {
      e.preventDefault();
      if (index >= 0) openViewer(index);
      return;
    }
    if (!(e.key in moves)) return;
    e.preventDefault();
    stepTo(index < 0 ? 0 : moves[e.key]);   // 아직 고른 사진이 없으면 첫 사진부터
  }

  film.addEventListener("keydown", (e) => {
    const item = e.target.closest(".film-item");
    if (!item || e.altKey || e.ctrlKey || e.metaKey) return;
    filmKey(e, indexById.get(Number(item.dataset.id)) ?? -1);
  });

  // 아무 곳에도 포커스가 없을 때(페이지 빈 곳을 누른 뒤 등)도 ← → 로 필름을 넘긴다.
  // 입력칸·지도(Leaflet 의 방향키 이동)·크게 보기 창에 포커스가 있으면 그쪽에 맡긴다.
  document.addEventListener("keydown", (e) => {
    if (viewer.open || diaryView.open || photos.length === 0 || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target !== document.body || e.key === "Enter") return;
    filmKey(e, selectedIndex());
  });

  // 필름에서 고르기: 위치가 있으면 지도에서 그 마커로 이동, 없으면 바로 크게 보기
  function selectPhoto(p) {
    highlight(p.pic_id);
    const marker = markers.get(p.pic_id);
    if (marker) cluster.zoomToShowLayer(marker, () => marker.openPopup());
    else openViewer(indexById.get(p.pic_id));
  }

  // 선택 강조 (필름 + 마커) — 전에 고른 것과 새로 고른 것 두 개만 바꾼다 (사진 수와 관계없이 일정)
  // 지금 화면에 없는 버튼·마커는 나중에 만들 때 selectedId 를 보고 강조된 모양으로 만든다
  function highlight(id) {
    const prev = selectedId;
    selectedId = id;
    if (prev !== null && prev !== id) setSelected(prev, false);
    setSelected(id, true);
    scrollFilmTo(id, true);
    syncTabStop();
  }

  function setSelected(id, on) {
    filmNodes.get(id)?.classList.toggle("is-selected", on);
    const marker = markers.get(id);
    if (marker) {
      marker.getElement()?.classList.toggle("is-selected", on);
      marker.setZIndexOffset(on ? 1000 : 0);
    }
  }

  // 사진 상태·설명이 바뀌었을 때 마커·필름 모양만 다시 그린다 (조회는 다시 하지 않음)
  function repaintPhoto(p) {
    markers.get(p.pic_id)?.setIcon(photoIcon(p));
    const el = filmItem(p.pic_id);
    if (el) el.className = photoClass("film-item", p);
  }

  // ============================================================
  // 사진 크게 보기 (이전/다음 · 상태 · 설명)
  // ============================================================
  const viewer = $("viewer");
  const pv = {
    img: $("pv-img"), prev: $("pv-prev"), next: $("pv-next"), count: $("pv-count"),
    time: $("pv-time"), name: $("pv-name"), loc: $("pv-loc"),
    when: $("pv-when"), timeEdit: $("pv-time-edit"), timeBox: $("pv-time-box"), timeIn: $("pv-time-in"),
    timeSave: $("pv-time-save"), timeCancel: $("pv-time-cancel"),
    locEdit: $("pv-loc-edit"), locBox: $("pv-loc-box"), locMapEl: $("pv-loc-map"),
    locSave: $("pv-loc-save"), locCancel: $("pv-loc-cancel"), locClear: $("pv-loc-clear"),
    status: $("pv-status"), statusMsg: $("pv-status-msg"),
    edit: $("pv-edit"), view: $("pv-view"), loading: $("pv-loading"),
    title: $("pv-title"), html: $("pv-html"), empty: $("pv-empty"), updated: $("pv-updated"),
    form: $("pv-form"), titleIn: $("pv-title-in"), preview: $("pv-preview"),
    // 설명 본문: 처음엔 기본 textarea. '쓰기'를 처음 누를 때 OverType 편집기를 불러와 바꿔 끼운다(ensureEditor)
    note: $("pv-note"),
    tabWrite: $("pv-tab-write"), tabPreview: $("pv-tab-preview"),
    error: $("pv-error"), del: $("pv-delete"), cancel: $("pv-cancel"), save: $("pv-save"),
    trash: $("pv-trash"),
  };
  let cur = -1;           // 보고 있는 사진 번호 (photos 배열 위치)
  let detail = null;      // 보고 있는 사진의 상세 (설명 포함)
  let detailSeq = 0;
  let editing = false;
  let saved = { title: "", note: "" };   // 편집 시작 시점 값 (바뀌었는지 비교용)
  let stale = false;      // 상태를 바꿔 지금 조건에서 빠진 사진이 있음 → 창을 닫으면 다시 조회

  let locMap = null;      // 위치 찍기용 작은 지도 (처음 열 때 만든다)
  let locPin = null;      // 위치 찍기 핀
  let locPending = null;  // 찍었지만 아직 저장하지 않은 위치 (L.LatLng)

  const noteDirty = () => editing && (pv.titleIn.value !== saved.title || pv.note.value !== saved.note);
  const locDirty = () => locPending !== null;
  let timeStart = "";     // 일시 수정 칸을 열 때의 값 (바뀌었는지 비교용)
  const timeDirty = () => !pv.timeBox.hidden && pv.timeIn.value !== timeStart;
  const isDirty = () => noteDirty() || locDirty() || timeDirty();
  function confirmDiscard() {
    if (!isDirty()) return true;
    const what = [noteDirty() && "설명", locDirty() && "위치", timeDirty() && "일시"].filter(Boolean).join(", ");
    return confirm(`저장하지 않은 ${what}이(가) 있습니다. 버릴까요?`);
  }

  function openViewer(index) {
    if (!(index >= 0 && index < photos.length)) return;   // undefined(목록에 없는 사진)도 막는다
    if (viewer.open && !confirmDiscard()) return;
    cur = index;
    const p = photos[cur];
    highlight(p.pic_id);
    pv.img.src = imageUrl(p);
    pv.img.alt = p.name || `${p.seq}번째 사진`;
    pv.count.textContent = `${p.seq} / ${photos.length}`;
    pv.prev.disabled = cur === 0;
    pv.next.disabled = cur === photos.length - 1;
    pv.time.textContent = `${p.seq}번째 · ${p.photo_at}`;
    pv.name.textContent = p.name;
    pv.status.value = p.status;
    showStatusMsg("");
    closeLocEditor();
    closeTimeEditor();
    renderLoc(p);
    setEditing(false);
    renderDesc(p, null, true);
    if (!viewer.open) viewer.showModal();
    loadDetail(p);
  }

  async function loadDetail(p) {
    const seq = ++detailSeq;
    try {
      const d = await api(photoUrl(p.pic_id));
      if (seq !== detailSeq) return;   // 그사이 다른 사진으로 넘어갔으면 버림
      detail = d;
      renderDesc(p, d.note, false);
      setHasNote(p, !!d.note);
    } catch (e) {
      if (seq !== detailSeq) return;
      pv.loading.hidden = false;
      pv.loading.textContent = `설명을 불러오지 못했습니다: ${e.message}`;
    }
  }

  // 설명 영역 그리기 (휴지통 사진은 설명을 숨기고 안내만)
  function renderDesc(p, note, loading) {
    const trashed = p.status === "D";
    pv.trash.hidden = !trashed;
    pv.edit.hidden = trashed || loading;
    pv.view.hidden = trashed;
    pv.loading.hidden = !loading;
    pv.loading.textContent = "불러오는 중…";
    pv.title.hidden = loading || !note || !note.title;
    pv.title.textContent = note?.title || "";
    pv.html.innerHTML = loading || !note ? "" : note.html;   // 서버가 nh3 로 살균한 HTML
    pv.empty.hidden = loading || !!note;
    pv.updated.hidden = loading || !note;
    pv.updated.textContent = note ? `${note.updated_at} 저장` : "";
    pv.edit.textContent = note ? "고치기" : "쓰기";
    if (!loading) detail = { ...(detail || {}), note };
  }

  // ── 편집 ──
  // OverType 는 처음 편집할 때만 불러온다 (지도만 보는 동안은 스크립트 약 135KB 를 메모리에 올리지 않음)
  // 불러오는 동안 textarea 에 쓴 글자는 그대로 넘어간다. 못 불러오면 textarea 를 계속 쓴다.
  let editorReady = null;
  function ensureEditor() {
    if (editorReady || !window.TPMd) return;
    editorReady = TPMd.load().then(() => {
      const ta = pv.note;
      const ed = TPMd.attach(ta, { theme: "auto", className: "pv-note-box" });
      if (ed === ta) return;
      ed.hidden = ta.hidden;
      pv.note = ed;
      if (editing && !ed.hidden) ed.focus();
    }).catch((e) => console.warn("기본 입력칸으로 설명을 씁니다.", e));
  }

  function setEditing(on) {
    editing = on;
    pv.form.hidden = !on;
    pv.view.hidden = on || photos[cur]?.status === "D";
    pv.edit.hidden = on || photos[cur]?.status === "D";
    pv.error.hidden = true;
    if (on) {
      const note = detail?.note;
      saved = { title: note?.title || "", note: note?.note || "" };
      pv.titleIn.value = saved.title;
      pv.note.value = saved.note;
      pv.del.hidden = !note;
      showTab("write");
      pv.note.focus();
      ensureEditor();
    }
  }

  function showTab(which) {
    const write = which === "write";
    pv.tabWrite.classList.toggle("is-on", write);
    pv.tabPreview.classList.toggle("is-on", !write);
    pv.tabWrite.setAttribute("aria-selected", write);
    pv.tabPreview.setAttribute("aria-selected", !write);
    pv.note.hidden = !write;
    pv.preview.hidden = write;
    if (!write) {
      pv.preview.innerHTML = '<p class="muted small">미리보기를 만드는 중…</p>';
      api(config.previewUrl, { method: "POST", body: JSON.stringify({ note: pv.note.value }) })
        .then((d) => { pv.preview.innerHTML = d.html || '<p class="muted small">내용이 없습니다.</p>'; })
        .catch((e) => { pv.preview.textContent = `미리보기 실패: ${e.message}`; });
    }
  }

  async function saveNote() {
    const p = photos[cur];
    if (!pv.note.value.trim()) {
      showError("설명 내용이 비어 있습니다.");
      return;
    }
    pv.save.disabled = true;
    try {
      await api(`${photoUrl(p.pic_id)}/note`, {
        method: "PUT",
        body: JSON.stringify({ title: pv.titleIn.value, note: pv.note.value }),
      });
      setEditing(false);
      renderDesc(p, null, true);
      await loadDetail(p);
    } catch (e) {
      showError(e.message);
    } finally {
      pv.save.disabled = false;
    }
  }

  async function deleteNote() {
    const p = photos[cur];
    if (!confirm("이 사진의 설명을 삭제할까요?")) return;
    try {
      await api(`${photoUrl(p.pic_id)}/note`, { method: "DELETE" });
      setEditing(false);
      renderDesc(p, null, false);
      setHasNote(p, false);
    } catch (e) {
      showError(e.message);
    }
  }

  // 설명 유무가 바뀌면 지도·필름 테두리를 바로 바꾼다
  function setHasNote(p, has) {
    if (p.has_note === has) return;
    p.has_note = has;
    repaintPhoto(p);
  }

  function showError(msg) {
    pv.error.textContent = msg;
    pv.error.hidden = false;
  }

  // ── 상태 변경 ──
  async function changeStatus() {
    const p = photos[cur];
    const next = pv.status.value;
    const before = p.status;
    if (next === before) return;
    if (next === "D" && !confirm("이 사진을 휴지통으로 옮길까요?\n(상태를 다시 바꾸면 복구할 수 있습니다)")) {
      pv.status.value = before;
      return;
    }
    if (next === "D" && editing && !confirmDiscard()) {
      pv.status.value = before;
      return;
    }
    pv.status.disabled = true;
    try {
      await api(photoUrl(p.pic_id), { method: "PATCH", body: JSON.stringify({ status: next }) });
      p.status = next;
      repaintPhoto(p);
      if (next === "D") { closeLocEditor(); closeTimeEditor(); }
      renderLoc(p);
      renderWhen(p);
      const left = !statusFilter().includes(next);
      if (left) stale = true;
      showStatusMsg(
        `'${STATUS_LABEL[next]}'(으)로 바꿨습니다.` +
        (left ? " 지금 조회 조건에는 없는 상태라 창을 닫으면 지도에서 빠집니다." : ""),
      );
      if (next === "D") {
        setEditing(false);
        renderDesc(p, null, false);
        setHasNote(p, false);
      } else if (before === "D") {            // 복구 → 숨겨졌던 설명을 다시 불러온다
        renderDesc(p, null, true);
        loadDetail(p);
      }
    } catch (e) {
      pv.status.value = before;
      showStatusMsg(`바꾸지 못했습니다: ${e.message}`, true);
    } finally {
      pv.status.disabled = false;
    }
  }

  function showStatusMsg(msg, isError = false) {
    pv.statusMsg.textContent = msg;
    pv.statusMsg.hidden = !msg;
    pv.statusMsg.classList.toggle("is-error", isError);
  }

  // ============================================================
  // 위치 찍기·수정 (크게 보기 안의 작은 지도)
  // ============================================================
  // 위치 표시 줄 + 버튼 이름 (휴지통 사진은 위치를 바꿀 수 없다 — 복구 후 가능)
  function renderLoc(p) {
    pv.loc.textContent = p.lat === null ? "없음" : `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}`;
    pv.locEdit.textContent = p.lat === null ? "위치 찍기" : "위치 수정";
    pv.locEdit.hidden = p.status === "D" || !pv.locBox.hidden;
  }

  // 위치 없는 사진의 시작 지점: 촬영 순서상 가장 가까운(앞뒤) 위치 있는 사진
  function nearestLocated(index) {
    for (let d = 1; d < photos.length; d++) {
      for (const i of [index - d, index + d]) {
        if (photos[i] && photos[i].lat !== null) return [photos[i].lat, photos[i].lng];
      }
    }
    return null;
  }

  function openLocEditor() {
    const p = photos[cur];
    pv.locBox.hidden = false;
    pv.locEdit.hidden = true;
    pv.locClear.hidden = p.lat === null;
    pv.locSave.disabled = true;
    locPending = null;
    if (!locMap) {
      locMap = L.map(pv.locMapEl, { zoomControl: true });
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", TILE_OPTS).addTo(locMap);
      locMap.on("click", (e) => placePin(e.latlng, true));
    }
    locMap.invalidateSize();   // 숨겨져 있던 칸이라 크기를 다시 재야 한다
    if (locPin) { locPin.remove(); locPin = null; }
    if (p.lat !== null) {
      locMap.setView([p.lat, p.lng], 16);
      placePin(L.latLng(p.lat, p.lng), false);
    } else {
      const near = nearestLocated(cur);
      if (near) locMap.setView(near, 14);
      else locMap.setView(map.getCenter(), map.getZoom());
    }
  }

  // 핀 놓기 (changed=true 면 저장할 위치로 기억)
  function placePin(latlng, changed) {
    if (!locPin) {
      locPin = L.marker(latlng, {
        draggable: true, keyboard: false,
        icon: L.divIcon({ className: "loc-pin", html: "", iconSize: [22, 22], iconAnchor: [11, 11] }),
      }).addTo(locMap);
      locPin.on("dragend", () => setPending(locPin.getLatLng()));
    } else {
      locPin.setLatLng(latlng);
    }
    if (changed) setPending(latlng);
  }

  function setPending(latlng) {
    locPending = latlng.wrap();   // 지도를 옆으로 돌려 찍어도 경도가 -180~180 안에 들게
    pv.locSave.disabled = false;
    pv.loc.textContent = `${locPending.lat.toFixed(5)}, ${locPending.lng.toFixed(5)} (저장 전)`;
  }

  function closeLocEditor() {
    locPending = null;
    pv.locBox.hidden = true;
    if (cur >= 0 && photos[cur]) renderLoc(photos[cur]);
  }

  // 저장(clear=true 면 위치 지우기) → 지도·필름·요약을 바로 다시 그린다 (조회는 다시 하지 않음)
  async function saveLocation(clear) {
    const p = photos[cur];
    if (clear && !confirm("이 사진의 위치를 지울까요?\n지도에서 빠지고 필름에는 '위치 없음'으로 남습니다.")) return;
    if (!clear && !locPending) return;
    const round = (v) => Math.round(v * 1e7) / 1e7;   // DB 컬럼(소수점 7자리)에 맞춘다
    const body = clear ? { latitude: null, longitude: null }
      : { latitude: round(locPending.lat), longitude: round(locPending.lng) };
    for (const b of [pv.locSave, pv.locClear, pv.locCancel]) b.disabled = true;
    try {
      const d = await api(photoUrl(p.pic_id), { method: "PATCH", body: JSON.stringify(body) });
      p.lat = d.lat;
      p.lng = d.lng;
      closeLocEditor();
      draw(photos, true);     // 마커·이동 경로·필름 다시 그리기 (지도 시점은 그대로)
      renderSummary();
      showStatusMsg(clear ? "위치를 지웠습니다." : "위치를 저장했습니다.");
    } catch (e) {
      showStatusMsg(`위치를 저장하지 못했습니다: ${e.message}`, true);
    } finally {
      for (const b of [pv.locSave, pv.locClear, pv.locCancel]) b.disabled = false;
      pv.locSave.disabled = !locPending;
    }
  }

  // ============================================================
  // 촬영 일시 수정 (EXIF 가 없어 파일 이름·업로드 시각으로 들어간 사진 바로잡기)
  // ============================================================
  function renderWhen(p) {
    pv.when.textContent = p.photo_at;
    pv.timeEdit.hidden = p.status === "D" || !pv.timeBox.hidden;   // 휴지통 사진은 복구한 뒤에
  }

  function openTimeEditor() {
    const p = photos[cur];
    // 상세(초까지)를 받았으면 그 값, 아직이면 분까지 값으로 채운다
    const full = detail && detail.pic_id === p.pic_id && detail.photo_at_full;
    timeStart = full || p.photo_at.replace(" ", "T");
    pv.timeIn.value = timeStart;
    pv.timeBox.hidden = false;
    renderWhen(p);
    pv.timeIn.focus();
  }

  function closeTimeEditor() {
    pv.timeBox.hidden = true;
    if (cur >= 0 && photos[cur]) renderWhen(photos[cur]);
  }

  // 저장 → 화면의 일시만 바로 바꾸고, 촬영 순서·날짜 목록은 창을 닫을 때 다시 조회해 맞춘다(stale)
  async function saveTime() {
    const p = photos[cur];
    const value = pv.timeIn.value;
    if (!value) { showStatusMsg("일시를 입력해 주세요.", true); return; }
    for (const b of [pv.timeSave, pv.timeCancel]) b.disabled = true;
    try {
      const d = await api(photoUrl(p.pic_id), { method: "PATCH", body: JSON.stringify({ photo_at: value }) });
      const changed = d.photo_at !== p.photo_at || d.base_dt !== p.base_dt;
      p.photo_at = d.photo_at;
      p.base_dt = d.base_dt;
      if (detail && detail.pic_id === p.pic_id) detail.photo_at_full = d.photo_at_full;
      stale = true;                           // 순서·날짜가 바뀌었을 수 있다
      closeTimeEditor();
      pv.time.textContent = `${p.seq}번째 · ${p.photo_at}`;
      showStatusMsg(changed ? "일시를 바꿨습니다. 창을 닫으면 촬영 순서가 다시 맞춰집니다." : "일시를 저장했습니다.");
    } catch (e) {
      showStatusMsg(`일시를 저장하지 못했습니다: ${e.message}`, true);
    } finally {
      for (const b of [pv.timeSave, pv.timeCancel]) b.disabled = false;
    }
  }

  // ── 닫기 ──
  function closeViewer() {
    if (confirmDiscard()) viewer.close();
  }

  // ── 크게 보기 이벤트 ──
  pv.prev.addEventListener("click", () => openViewer(cur - 1));
  pv.next.addEventListener("click", () => openViewer(cur + 1));
  pv.status.addEventListener("change", changeStatus);
  pv.edit.addEventListener("click", () => setEditing(true));
  pv.cancel.addEventListener("click", () => {
    if (!noteDirty() || confirm("저장하지 않은 설명이 있습니다. 버릴까요?")) setEditing(false);
  });
  pv.timeEdit.addEventListener("click", openTimeEditor);
  pv.timeCancel.addEventListener("click", closeTimeEditor);
  pv.timeSave.addEventListener("click", saveTime);
  pv.timeIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveTime(); }
  });
  pv.locEdit.addEventListener("click", openLocEditor);
  pv.locCancel.addEventListener("click", closeLocEditor);
  pv.locSave.addEventListener("click", () => saveLocation(false));
  pv.locClear.addEventListener("click", () => saveLocation(true));
  pv.del.addEventListener("click", deleteNote);
  pv.tabWrite.addEventListener("click", () => showTab("write"));
  pv.tabPreview.addEventListener("click", () => showTab("preview"));
  pv.form.addEventListener("submit", (e) => { e.preventDefault(); saveNote(); });
  pv.form.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveNote(); }
  });
  for (const btn of viewer.querySelectorAll("[data-close]")) btn.addEventListener("click", closeViewer);
  viewer.addEventListener("cancel", (e) => {            // Esc
    if (!confirmDiscard()) e.preventDefault();
    else editing = false;
  });
  viewer.addEventListener("click", (e) => { if (e.target === viewer) closeViewer(); }); // 바깥 누르면 닫기
  viewer.addEventListener("keydown", (e) => {
    // 입력 중이 아니고 위치 찍기 지도(방향키로 지도 이동)도 아닐 때만 ← → 로 촬영순 넘기기
    if (e.target.closest("input, textarea, select, .leaflet-container")) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); openViewer(cur - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); openViewer(cur + 1); }
  });
  viewer.addEventListener("close", () => {
    editing = false;
    closeLocEditor();
    closeTimeEditor();
    detailSeq++;
    pv.img.removeAttribute("src");
    const p = photos[cur];
    if (p) focusFilm(p.pic_id);           // 닫은 뒤 바로 ← → 로 이어서 넘길 수 있게
    if (stale) {                        // 조건에서 빠진 사진이 있으면 날짜 목록과 지도를 다시 조회
      stale = false;
      refresh(true);
    } else if (p && markers.get(p.pic_id)) {
      highlight(p.pic_id);
      map.panTo(markers.get(p.pic_id).getLatLng());
    }
  });

  // ============================================================
  // 화면 이벤트
  // ============================================================
  $("range-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (startInput.value && endInput.value) search(fromInput(startInput.value), fromInput(endInput.value));
  });
  $("all-btn").addEventListener("click", searchAll);
  for (const input of statusInputs) input.addEventListener("change", () => refresh(false));
  routeToggle.addEventListener("change", () => {
    if (!routeLine) return;
    if (routeToggle.checked) routeLine.addTo(map);
    else routeLine.remove();
  });

  // '전체': 사진이 있는 가장 이른 날 ~ 가장 늦은 날로 기간을 넓혀 조회
  async function searchAll() {
    if (statusFilter().length === 0) return search(range.start, range.end);
    let all;
    try {
      all = (await api(`${config.datesUrl}?status=${statusFilter().join(",")}`)).dates;   // 최근 날짜부터
    } catch (e) {
      summary.textContent = `불러오지 못했습니다: ${e.message}`;
      return;
    }
    if (all.length === 0) {
      summary.textContent = "조건에 맞는 사진이 아직 없습니다.";
      return;
    }
    search(all[all.length - 1].base_dt, all[0].base_dt);
  }

  // 상태 조건이 바뀌었거나 사진 상태를 바꾼 뒤: 같은 기간·같은 날로 다시 조회
  function refresh(keepView) {
    search(range.start, range.end, { keepView, day: focusDay });
  }

  function getAccent() {
    return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2f6f5e";
  }

  // ── 시작: 주소의 기간·상태(없으면 이번 달 1일 ~ 오늘)로 조회 ──
  (function init() {
    const q = new URLSearchParams(location.search);
    if (q.get("status")) setStatusFilter(q.get("status").toUpperCase().split(","));
    const valid = (v) => /^\d{8}$/.test(v || "");
    const r = valid(q.get("start")) && valid(q.get("end"))
      ? { start: q.get("start"), end: q.get("end") }
      : defaultRange();
    search(r.start, r.end, { day: valid(q.get("day")) ? q.get("day") : null });
  })();
})();

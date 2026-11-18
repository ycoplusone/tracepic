// 공용: 하루 동선 지도 + 사진 크게 보기(라이트박스)
// - 일기 읽기 창(diary.js)과 여행기 화면(story.js)이 같이 쓴다. Leaflet(L)이 먼저 로드되어 있어야 한다(지도만).
// - 사진 형식은 /api 의 사진 JSON(지도 화면과 같음): pic_id, photo_at, lat/lng(null 가능), status, has_note,
//   mini_url, thumb_url, image_url. 순번(seq)은 넘겨받은 목록 안에서 1부터 — 위치 없는 사진도 번호를 차지한다.
// - 마커 모양은 지도 화면과 같다 (.photo-marker: 테두리 = 상태, 보라 바깥 테두리 = 설명, 왼쪽 위 = 순번).
window.TPDay = (function () {
  "use strict";

  const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

  function accent() {
    return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2f6f5e";
  }

  function markerIcon(p, seq) {
    const box = document.createElement("div");
    const img = document.createElement("img");
    img.src = p.mini_url || p.thumb_url;
    img.alt = "";
    const num = document.createElement("span");
    num.className = "seq";
    num.textContent = seq;
    box.append(img, num);
    const cls = `photo-marker st-${p.status}${p.has_note ? " has-note" : ""}`;
    return L.divIcon({ className: cls, html: box, iconSize: [48, 48], iconAnchor: [24, 24] });
  }

  // ============================================================
  // 동선 지도: 위치 있는 사진을 순번 마커로 찍고 촬영순으로 점선을 잇는다
  // - 위치 있는 사진이 없으면 지도를 만들지 않고 null
  // - onSelect(index): 마커를 누르면 photos 안의 위치를 알려 준다
  // - 반환값 { map, select(index), remove() }
  // ============================================================
  function dayMap(el, photos, { onSelect } = {}) {
    const located = photos.map((p, i) => ({ p, i })).filter((x) => x.p.lat !== null && x.p.lat !== undefined);
    if (located.length === 0) return null;
    // 페이지를 스크롤하다 지도가 확대되지 않도록 휠 확대는 끈다 (버튼·두 손가락으로 확대)
    const map = L.map(el, { scrollWheelZoom: false });
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: TILE_ATTR }).addTo(map);
    const latlngs = located.map((x) => [x.p.lat, x.p.lng]);
    if (latlngs.length > 1) {
      L.polyline(latlngs, { color: accent(), weight: 3, opacity: 0.7, dashArray: "6 6" }).addTo(map);
    }
    const markers = new Map();   // photos 위치 → 마커
    for (const { p, i } of located) {
      const m = L.marker([p.lat, p.lng], { icon: markerIcon(p, i + 1), title: `${i + 1}. ${p.photo_at}` }).addTo(map);
      m.on("click", () => onSelect && onSelect(i));
      markers.set(i, m);
    }
    const fit = () => {
      map.invalidateSize();
      map.fitBounds(L.latLngBounds(latlngs), { padding: [36, 36], maxZoom: 16 });
    };
    fit();
    // 창(dialog)이 열리며 크기가 바뀌는 경우가 있어 한 번 더 맞춘다
    requestAnimationFrame(fit);
    return {
      map,
      fit,
      // 강조: 고른 사진 마커를 앞으로, 지도 안에 보이게
      select(index) {
        for (const [i, m] of markers) {
          m.getElement()?.classList.toggle("is-selected", i === index);
          m.setZIndexOffset(i === index ? 1000 : 0);
        }
        const m = markers.get(index);
        if (m && !map.getBounds().contains(m.getLatLng())) map.panTo(m.getLatLng());
      },
      remove() { map.remove(); },
    };
  }

  // ============================================================
  // 사진 크게 보기 (라이트박스): 사진만 크게, ← → 로 넘기기, Esc 로 닫기
  // - photos 안의 index 부터 연다. caption(p, index) 로 아래 설명 문구를 정할 수 있다.
  // - onChange(index): 넘길 때마다 알려 준다 (지도 마커 강조 등)
  // ============================================================
  let box = null;
  function ensureBox() {
    if (box) return box;
    const dlg = document.createElement("dialog");
    dlg.className = "lightbox";
    dlg.setAttribute("aria-label", "사진 크게 보기");
    dlg.innerHTML = `
      <img class="lb-img" alt="">
      <button type="button" class="lb-nav prev" aria-label="이전 사진">‹</button>
      <button type="button" class="lb-nav next" aria-label="다음 사진">›</button>
      <button type="button" class="lb-close" aria-label="닫기">×</button>
      <div class="lb-cap"></div>`;
    document.body.append(dlg);
    box = {
      dlg, img: dlg.querySelector(".lb-img"), cap: dlg.querySelector(".lb-cap"),
      prev: dlg.querySelector(".prev"), next: dlg.querySelector(".next"),
      photos: [], index: 0, caption: null, onChange: null,
    };
    const show = (i) => {
      if (i < 0 || i >= box.photos.length) return;
      box.index = i;
      const p = box.photos[i];
      box.img.src = p.image_url;
      box.img.alt = `${i + 1}번째 사진`;
      box.cap.textContent = box.caption ? box.caption(p, i) : `${i + 1} / ${box.photos.length} · ${p.photo_at}`;
      box.prev.disabled = i === 0;
      box.next.disabled = i === box.photos.length - 1;
      if (box.onChange) box.onChange(i);
    };
    box.show = show;
    box.prev.addEventListener("click", () => show(box.index - 1));
    box.next.addEventListener("click", () => show(box.index + 1));
    dlg.querySelector(".lb-close").addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // 바깥(배경) 누르면 닫기
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); show(box.index - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); show(box.index + 1); }
    });
    dlg.addEventListener("close", () => box.img.removeAttribute("src"));
    return box;
  }

  function lightbox(photos, index, { caption, onChange } = {}) {
    const b = ensureBox();
    b.photos = photos;
    b.caption = caption || null;
    b.onChange = onChange || null;
    if (!b.dlg.open) b.dlg.showModal();
    b.show(index);
    b.dlg.querySelector(".lb-close").focus({ preventScroll: true });
  }

  // 날짜 표시: 20261103 → "2026년 11월 3일 화요일"
  const DOW = ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];
  function longDate(dt) {
    const d = new Date(+dt.slice(0, 4), +dt.slice(4, 6) - 1, +dt.slice(6, 8));
    return `${dt.slice(0, 4)}년 ${+dt.slice(4, 6)}월 ${+dt.slice(6, 8)}일 ${DOW[d.getDay()]}`;
  }

  // 지도 화면 주소 (그 하루만 조회)
  const mapUrl = (dt) => `/?start=${dt}&end=${dt}`;

  return { dayMap, lightbox, longDate, mapUrl };
})();

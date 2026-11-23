/* ============================================================
   상단 메뉴 접기·펼치기 (좁은 화면 전용)
   - 720px 이하에서는 메뉴가 접혀 있고 ☰ 버튼으로 펼친다. 넓은 화면에서는 버튼이 숨고 메뉴가 늘 보인다(CSS).
   - 메뉴를 누르거나 Esc, 메뉴 바깥을 누르면 접힌다.
   ============================================================ */
(function () {
  "use strict";
  const btn = document.getElementById("nav-toggle");
  const bar = btn && btn.closest(".topbar");
  if (!bar) return;

  function setOpen(open) {
    bar.classList.toggle("is-open", open);
    btn.setAttribute("aria-expanded", String(open));
    btn.setAttribute("aria-label", open ? "메뉴 접기" : "메뉴 펼치기");
    btn.firstElementChild.textContent = open ? "✕" : "☰";
  }

  btn.addEventListener("click", () => setOpen(!bar.classList.contains("is-open")));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && bar.classList.contains("is-open")) { setOpen(false); btn.focus(); }
  });
  document.addEventListener("click", (e) => {
    if (bar.classList.contains("is-open") && !bar.contains(e.target)) setOpen(false);
  });
})();

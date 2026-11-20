/* ============================================================
   마크다운 편집기 (OverType) 공용 연결 — 일기 · 사진 설명이 같이 쓴다
   - 기존 <textarea> 자리에 OverType 편집기를 끼우고, textarea 와 같은 모양의 객체
     (value / hidden / focus / addEventListener)를 돌려준다. 그래서 diary.js · map.js 는
     textarea 를 쓰던 코드를 거의 그대로 쓴다.
   - OverType 스크립트를 못 불러오면 원래 textarea 를 그대로 돌려준다(그냥 글자 입력).
   - 저장 형식은 그대로 마크다운 글자이고, 미리보기·화면 표시는 계속 서버(utils/md.render, nh3)가 만든다.
   ============================================================ */
(function () {
  "use strict";

  // 툴바: OverType 기본 버튼을 골라 한국어 설명을 붙인다 (보기 전환 버튼은 뺌 — 미리보기는 서버 탭을 쓴다)
  const LABELS = [
    ["bold", "굵게 (Ctrl+B)"], ["italic", "기울임 (Ctrl+I)"], ["separator"],
    ["h2", "제목"], ["h3", "작은 제목"], ["separator"],
    ["bulletList", "글머리 목록"], ["orderedList", "번호 목록"], ["taskList", "할 일 목록"],
    ["quote", "인용"], ["separator"], ["link", "링크"],
  ];

  function toolbar() {
    const all = window.toolbarButtons;          // overtype.min.js 가 전역에 둔다
    if (!all) return undefined;                 // 없으면 OverType 기본 툴바
    return LABELS.map(([name, title]) => (all[name] ? { ...all[name], ...(title ? { title } : {}) } : null))
      .filter(Boolean);
  }

  /**
   * textarea 를 OverType 편집기로 바꾼다.
   * @param {HTMLTextAreaElement} textarea 바꿀 입력칸 (placeholder · 값 · id · aria-label 을 넘겨받는다)
   * @param {object} opts { theme: "solar" | "cave" | "auto", className: 편집기 상자에 붙일 클래스 }
   * @returns textarea 처럼 쓸 수 있는 객체 (실패하면 textarea 그대로)
   */
  function attach(textarea, opts = {}) {
    if (!textarea || typeof window.OverType !== "function") return textarea;

    const box = document.createElement("div");
    box.className = "md-editor " + (opts.className || "");
    textarea.before(box);

    let ot;
    try {
      [ot] = new window.OverType(box, {
        value: textarea.value,
        placeholder: textarea.placeholder,
        theme: opts.theme || "auto",
        toolbar: true,
        toolbarButtons: toolbar(),
        smartLists: true,                       // 목록에서 Enter → 다음 항목 자동
        spellcheck: false,
        fontSize: "15px",
        lineHeight: 1.7,
        padding: "12px",
        // 위·아래 두 겹의 글자 위치를 맞추려면 고정폭 글꼴이어야 한다 (한글은 각 기기의 고정폭/한글 글꼴로)
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "D2Coding", "Noto Sans Mono CJK KR", monospace',
        mobile: { fontSize: "16px", padding: "10px", lineHeight: 1.6 },   // 16px 미만이면 iOS 가 확대함
        textareaProps: { id: textarea.id, "aria-label": textarea.getAttribute("aria-label") || "본문" },
      });
    } catch (e) {
      console.warn("마크다운 편집기를 만들지 못해 기본 입력칸을 씁니다.", e);
      box.remove();
      return textarea;
    }
    textarea.remove();                          // id 는 OverType 의 textarea 가 넘겨받았다

    return {
      editor: ot,
      box,
      get value() { return ot.getValue(); },
      set value(v) { ot.setValue(v == null ? "" : String(v)); },
      get hidden() { return box.hidden; },
      set hidden(h) { box.hidden = !!h; },
      focus() { ot.focus(); },
      addEventListener(type, fn, o) { ot.textarea.addEventListener(type, fn, o); },
    };
  }

  window.TPMd = { attach };
})();

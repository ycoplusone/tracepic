// 사진 업로드 화면 스크립트
// - 선택(또는 끌어다 놓은) 파일을 한 장씩 POST /photos/upload 로 보낸다 (동시에 최대 2장).
// - 파일마다 진행률·결과(촬영 시각, 위치 유무, 썸네일)를 목록에 보여 준다.
// - 동영상(mp4·mov 등)은 서버가 3~7초 구간만 움직이는 WebP 로 바꿔 저장한다(영상은 보관 안 함). 다 올라간 뒤 '변환 중'을 보여 준다.
// - CSRF 토큰은 <meta name="csrf-token"> 에서 읽어 X-CSRF-Token 헤더로 보낸다.
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("upload-config").textContent);
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const input = document.getElementById("file-input");
  const dropzone = document.getElementById("dropzone");
  const list = document.getElementById("upload-list");
  const summary = document.getElementById("summary");
  const doneActions = document.getElementById("done-actions");
  const statusSelect = document.getElementById("status");

  const CONCURRENCY = 2;   // 동시에 올리는 파일 수 (서버·회선 부담 조절)
  const queue = [];        // 아직 보내지 않은 { file, row } 목록
  let active = 0;
  let stats = { total: 0, ok: 0, fail: 0 };

  // ── 파일 선택 / 끌어다 놓기 ──
  // 사진첩(#file-input) · 파일 탐색기(#file-input-raw, 위치 유지용) 두 입력을 같은 방식으로 처리
  for (const el of [input, document.getElementById("file-input-raw")]) {
    if (!el) continue;
    el.addEventListener("change", () => {
      addFiles(el.files);
      el.value = ""; // 같은 파일을 다시 고를 수 있게 초기화
    });
  }
  ["dragenter", "dragover"].forEach((type) =>
    dropzone.addEventListener(type, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-over");
    })
  );
  ["dragleave", "drop"].forEach((type) =>
    dropzone.addEventListener(type, (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-over");
    })
  );
  dropzone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  // 페이지를 떠나면 진행 중인 업로드가 끊기므로 경고
  window.addEventListener("beforeunload", (e) => {
    if (active > 0 || queue.length > 0) e.preventDefault();
  });

  function addFiles(fileList) {
    for (const file of fileList) {
      const row = makeRow(file);
      stats.total += 1;
      const limit = isVideo(file) ? config.maxVideoBytes : config.maxBytes;
      if (isVideo(file) && !config.videoSupported) {
        finish(row, false, "이 서버에서는 동영상을 올릴 수 없습니다 (ffmpeg 없음)");
        continue;
      }
      if (file.size > limit) {
        finish(row, false, `파일이 너무 큽니다 (최대 ${Math.round(limit / 1048576)}MB)`);
        continue;
      }
      queue.push({ file, row });
    }
    updateSummary();
    pump();
  }

  // 대기열에서 꺼내 동시 업로드 수를 채운다
  function pump() {
    while (active < CONCURRENCY && queue.length > 0) {
      const job = queue.shift();
      active += 1;
      upload(job.file, job.row).finally(() => {
        active -= 1;
        updateSummary();
        pump();
      });
    }
  }

  // 파일 1장 업로드 (진행률 표시를 위해 fetch 대신 XMLHttpRequest 사용)
  function upload(file, row) {
    return new Promise((resolve) => {
      const form = new FormData();
      form.append("photo", file);
      form.append("status", statusSelect.value);
      form.append("client_time", localIso(file.lastModified)); // EXIF 시각이 없을 때 대신 쓸 값
      form.append("tz_offset", String(-new Date().getTimezoneOffset())); // 동영상 UTC 촬영 시각 → 현지 시각용 (동쪽 +분)

      const xhr = new XMLHttpRequest();
      xhr.open("POST", config.uploadUrl);
      xhr.setRequestHeader("X-CSRF-Token", csrfToken);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.responseType = "json";

      row.state.textContent = "올리는 중…";
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) row.bar.value = Math.round((e.loaded / e.total) * 100);
      });
      // 다 올라간 뒤 서버가 처리하는 동안 (동영상은 WebP 변환에 수십 초 걸릴 수 있음)
      xhr.upload.addEventListener("load", () => {
        row.state.textContent = isVideo(file) ? "3~7초 구간을 움직이는 그림으로 변환 중…" : "처리 중…";
        row.bar.removeAttribute("value");   // 진행률을 모를 때의 막대
      });
      xhr.addEventListener("load", () => {
        const data = xhr.response;
        if (xhr.status === 200 && data && data.ok) {
          finish(row, true, describe(data));
          showThumb(row, data);
        } else if (data && data.error) {
          finish(row, false, data.error);
        } else if (xhr.responseURL && xhr.responseURL.includes("/login")) {
          finish(row, false, "로그인이 만료되었습니다. 다시 로그인해 주세요.");
        } else {
          finish(row, false, `업로드 실패 (HTTP ${xhr.status})`);
        }
        resolve();
      });
      xhr.addEventListener("error", () => {
        finish(row, false, "네트워크 오류로 업로드하지 못했습니다.");
        resolve();
      });
      xhr.send(form);
    });
  }

  // 성공 결과 설명: 촬영 시각(출처) + 위치 유무
  function describe(data) {
    const source = { exif: "", meta: "", file: " (파일 수정 시각)", upload: " (업로드 시각)" }[data.time_source] || "";
    const place = data.latitude !== null ? "위치 있음" : "위치 없음";
    const clip = data.kind === "clip" ? "🎞 동영상 3~7초 · " : "";
    return `${clip}${data.photo_at}${source} · ${place}`;
  }

  function makeRow(file) {
    const li = document.createElement("li");
    li.className = "upload-item";
    const thumb = document.createElement("div");
    thumb.className = "thumb";
    const body = document.createElement("div");
    body.className = "body";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = file.name; // textContent: 파일명에 HTML 이 있어도 안전
    const bar = document.createElement("progress");
    bar.max = 100;
    bar.value = 0;
    const state = document.createElement("div");
    state.className = "state muted small";
    state.textContent = "대기 중";
    body.append(name, bar, state);
    li.append(thumb, body);
    list.prepend(li);
    return { li, thumb, bar, state };
  }

  function finish(row, ok, message) {
    row.bar.remove();
    row.state.textContent = message;
    row.li.classList.add(ok ? "is-ok" : "is-fail");
    if (ok) stats.ok += 1;
    else stats.fail += 1;
    updateSummary();
  }

  function showThumb(row, data) {
    const img = document.createElement("img");
    img.src = data.thumb_url;
    img.alt = "";
    img.loading = "lazy";
    row.thumb.append(img);
  }

  function updateSummary() {
    if (stats.total === 0) return;
    const doneCount = stats.ok + stats.fail;
    summary.hidden = false;
    summary.textContent =
      doneCount < stats.total
        ? `${stats.total}장 중 ${doneCount}장 처리됨…`
        : `완료: 성공 ${stats.ok}장${stats.fail ? `, 실패 ${stats.fail}장` : ""}`;
    doneActions.hidden = doneCount < stats.total;
  }

  // 동영상인지 (MIME 이 비어 있는 브라우저도 있어 확장자도 본다)
  function isVideo(file) {
    if (file.type && file.type.startsWith("video/")) return true;
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    return config.videoExts.includes(ext);
  }

  // 밀리초 타임스탬프 → 사용자 기기 현지 시각 'YYYY-MM-DDTHH:MM:SS'
  function localIso(ms) {
    const d = new Date(ms);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
})();

(() => {
  const LANG_KEY = "gta6ar-lang";
  const html = document.documentElement;

  const monthsAr = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
  };

  const state = {
    lang: html.lang === "en" ? "en" : "ar",
    data: {
      overall: 0,
      areas: [
        { id: "translation", percent: 0, ar: "الترجمة", en: "Translation" },
        { id: "voice", percent: 0, ar: "الدبلجة", en: "Voice" },
        { id: "images", percent: 0, ar: "الصور", en: "Images" },
        { id: "fonts", percent: 0, ar: "الخطوط", en: "Fonts" },
        { id: "tools", percent: 0, ar: "الأدوات", en: "Tools" },
        { id: "qa", percent: 0, ar: "الجودة", en: "QA" }
      ],
      milestones: []
    }
  };

  // Both languages are in the markup (data-l="ar" / data-l="en"); CSS shows
  // the one matching <html lang>. This only flips the switch and remembers it.
  function applyLang() {
    const lang = state.lang;
    html.lang = lang;
    html.dir = lang === "en" ? "ltr" : "rtl";
    const title = html.getAttribute(`data-title-${lang}`);
    if (title) document.title = title;
    const toggle = document.getElementById("lang-toggle");
    if (toggle) {
      toggle.textContent = lang === "en" ? "العربية" : "English";
      toggle.setAttribute("aria-label", lang === "en" ? "التبديل إلى العربية" : "Switch to English");
    }
    renderProgress();
    renderTimeline();
  }

  function formatDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    if (state.lang === "en") {
      return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: "UTC"
      });
    }
    return `${d} ${monthsAr[m]} ${y}`;
  }

  function setBar(fill, pct) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        fill.style.width = `${pct}%`;
      });
    });
  }

  function renderProgress() {
    const list = document.getElementById("progress-list");
    if (!list) return;
    const overallLabel = state.lang === "en" ? "Overall" : "الكلي";
    const overall = Math.max(0, Math.min(100, Number(state.data.overall) || 0));
    document.getElementById("overall-value").textContent = `${overall}%`;
    const overallTrack = document.getElementById("overall-track");
    overallTrack.setAttribute("aria-valuenow", String(overall));
    overallTrack.setAttribute("aria-label", `${overallLabel} ${overall}%`);
    setBar(document.getElementById("overall-fill"), overall);
    list.innerHTML = "";
    state.data.areas.forEach((area) => {
      const pct = Math.max(0, Math.min(100, Number(area.percent) || 0));
      const row = document.createElement("div");
      row.className = "progress-row";
      row.innerHTML = `
        <span class="label"></span>
        <div class="bar-track" role="progressbar" aria-valuemin="0" aria-valuemax="100">
          <div class="bar-fill"></div>
        </div>
        <span class="pct"></span>
      `;
      const label = state.lang === "en" ? area.en : area.ar;
      row.querySelector(".label").textContent = label;
      const track = row.querySelector(".bar-track");
      track.setAttribute("aria-valuenow", String(pct));
      track.setAttribute("aria-label", `${label} ${pct}%`);
      row.querySelector(".pct").textContent = `${pct}%`;
      list.appendChild(row);
      setBar(row.querySelector(".bar-fill"), pct);
    });
  }

  function renderTimeline() {
    const ol = document.getElementById("timeline");
    if (!ol) return;
    ol.innerHTML = "";
    (state.data.milestones || []).forEach((ms) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <span class="node" aria-hidden="true"></span>
        <div class="ms-card">
          <a></a>
          <span class="sub"></span>
          <span class="when"></span>
        </div>
      `;
      li.querySelector(".when").textContent = formatDate(ms.due);
      const a = li.querySelector("a");
      a.href = ms.url;
      a.textContent = state.lang === "en" ? ms.en : ms.ar;
      li.querySelector(".sub").textContent = state.lang === "en" ? ms.ar : ms.en;
      ol.appendChild(li);
    });
  }

  async function loadProgress() {
    if (!document.getElementById("progress-list")) return;
    try {
      const res = await fetch("progress.json", { cache: "no-store" });
      if (!res.ok) throw new Error("progress.json missing");
      const data = await res.json();
      if (data.areas) state.data.areas = data.areas;
      if (typeof data.overall === "number") state.data.overall = data.overall;
      if (data.milestones) state.data.milestones = data.milestones;
    } catch (err) {
      console.warn("Using built-in progress fallback.", err);
    }
    renderProgress();
    renderTimeline();
  }

  // Counts down to launch day in the visitor's own time zone, then steps aside.
  function startCountdown() {
    const box = document.getElementById("countdown");
    if (!box) return;
    const target = new Date(box.dataset.target).getTime();
    const cells = {
      days: box.querySelector("[data-unit='days']"),
      hours: box.querySelector("[data-unit='hours']"),
      minutes: box.querySelector("[data-unit='minutes']"),
      seconds: box.querySelector("[data-unit='seconds']")
    };
    const before = document.getElementById("countdown-before");
    const after = document.getElementById("countdown-after");
    let timer = 0;
    function tick() {
      const left = target - Date.now();
      if (!(left > 0)) {
        box.hidden = true;
        if (before) before.hidden = true;
        if (after) after.hidden = false;
        clearInterval(timer);
        return;
      }
      const s = Math.floor(left / 1000);
      cells.days.textContent = String(Math.floor(s / 86400));
      cells.hours.textContent = String(Math.floor((s % 86400) / 3600)).padStart(2, "0");
      cells.minutes.textContent = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
      cells.seconds.textContent = String(s % 60).padStart(2, "0");
    }
    tick();
    timer = setInterval(tick, 1000);
  }

  const toggle = document.getElementById("lang-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      state.lang = state.lang === "ar" ? "en" : "ar";
      try { localStorage.setItem(LANG_KEY, state.lang); } catch (err) { /* private mode */ }
      applyLang();
    });
  }

  applyLang();
  loadProgress();
  startCountdown();
})();

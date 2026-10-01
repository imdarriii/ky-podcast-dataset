const FALLBACK = {
  SPEAKER_00: { name: "SPEAKER_00", role: "", klass: "guest" },
  SPEAKER_01: { name: "SPEAKER_01", role: "", klass: "host" },
};

const fmtClock = (sec) => {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
};

const clipDur = (c) => {
  if (c.duration_sec != null) return Number(c.duration_sec);
  return Math.max(0, Number(c.end_sec) - Number(c.start_sec));
};

const escapeHtml = (s) => String(s)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");

let catalog = null;
let current = null;
let data = null;
let filter = "all";
let query = "";

const speakerMeta = (id) => (current && current.speakers && current.speakers[id]) || FALLBACK[id] || { name: id, role: "", klass: "" };

const audioSrc = (clip) => {
  const prefix = current.audio_prefix || "./audio/";
  return prefix + String(clip.audio || clip.filename).replace(/\.wav$/i, ".opus");
};

async function load() {
  catalog = await (await fetch("./catalog.json")).json();
  const wanted = new URLSearchParams(location.search).get("id");
  if (!wanted) {
    renderHome();
    return;
  }
  current = catalog.podcasts.find((p) => p.id === wanted);
  if (!current) {
    renderHome();
    return;
  }
  data = await (await fetch(current.json)).json();
  filter = "all";
  query = "";
  renderDetail();
  renderRows();
}

function renderHome() {
  document.title = "ky-podcast-dataset";
  document.getElementById("home").classList.remove("hidden");
  document.getElementById("detail").classList.add("hidden");
  const totalClips = catalog.podcasts.reduce((sum, p) => sum + (Number(p.num_clips) || 0), 0);
  document.getElementById("home-sub").textContent =
    `${catalog.podcasts.length} выпусков · ${totalClips} реплик. Выбери выпуск — реплики идут одной линией, по времени.`;
  document.getElementById("home-tags").innerHTML = [
    ["language", "ky"],
    ["podcasts", String(catalog.podcasts.length)],
    ["реплики", String(totalClips)],
  ].map(([k, v]) => `<span class="tag"><b>${k}</b> ${v}</span>`).join("");

  document.getElementById("shows").innerHTML = catalog.podcasts.map((p, i) => {
    const n = Number(p.num_clips) || 0;
    return `<a class="show-line" href="./?id=${encodeURIComponent(p.id)}">
      <span class="show-n">${String(i + 1).padStart(2, "0")}</span>
      <strong>${escapeHtml(p.title)}</strong>
      <span class="show-count">${n} реплик</span>
    </a>`;
  }).join("");
}

function renderDetail() {
  document.title = `${current.title} · ky-podcast-dataset`;
  document.getElementById("home").classList.add("hidden");
  document.getElementById("detail").classList.remove("hidden");
  document.getElementById("page-title").textContent = current.title;
  const n = (data.clips || []).length;
  const speech = data.duration_sec || (data.clips || []).reduce((a, c) => a + clipDur(c), 0);
  document.getElementById("page-sub").textContent =
    `${n} реплик · ${fmtClock(speech)} речи · NeMo + GigaAM`;

  document.getElementById("tags").innerHTML = [
    ["language", "ky"],
    ["speakers", "2"],
    ["size", `${n} rows`],
  ].map(([k, v]) => `<span class="tag"><b>${k}</b> ${v}</span>`).join("");

  document.getElementById("people").innerHTML = Object.entries(current.speakers || {}).map(([id, s]) =>
    `<div class="person ${s.klass || ""}"><b>${escapeHtml(s.name)}</b><span>${escapeHtml(s.role || id)}</span></div>`
  ).join("");

  const jsonLink = document.getElementById("dl-json");
  jsonLink.href = current.json;
  jsonLink.setAttribute("download", `${current.id}.json`);
  const zip = document.getElementById("dl-zip");
  if (current.folder_zip) {
    zip.href = current.folder_zip;
    zip.style.display = "";
  } else {
    zip.style.display = "none";
  }
  const yt = document.getElementById("yt");
  yt.href = current.youtube_url;

  const ids = [...new Set((data.clips || []).map((c) => c.speaker))];
  const filters = document.getElementById("filters");
  filters.innerHTML = [
    `<button class="on" data-filter="all">all</button>`,
    ...ids.map((id) => `<button data-filter="${id}">${speakerMeta(id).name}</button>`),
  ].join("");
  filters.querySelectorAll("button").forEach((btn) => {
    btn.onclick = () => {
      filter = btn.dataset.filter;
      filters.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
      renderRows();
    };
  });

  document.getElementById("q").value = "";
  document.getElementById("q").oninput = (e) => {
    query = e.target.value.trim().toLowerCase();
    renderRows();
  };

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t === tab));
      document.getElementById("panel-viewer").classList.toggle("hidden", tab.dataset.tab !== "viewer");
      document.getElementById("panel-card").classList.toggle("hidden", tab.dataset.tab !== "card");
    };
  });
}

function filteredClips() {
  return (data.clips || []).filter((c) => {
    if (filter !== "all" && c.speaker !== filter) return false;
    if (!query) return true;
    const who = speakerMeta(c.speaker);
    const blob = [c.text, c.speaker, who.name, who.role, c.start_sec, c.audio].join(" ").toLowerCase();
    return blob.includes(query);
  }).sort((a, b) => (Number(a.start_sec) || 0) - (Number(b.start_sec) || 0));
}

function renderRows() {
  const all = filteredClips();
  const body = document.getElementById("rows");
  body.innerHTML = all.map((c, i) => {
    const who = speakerMeta(c.speaker);
    const dur = clipDur(c);
    const src = audioSrc(c);
    return `<li>
      <span class="n">${c.id || i + 1}</span>
      <div class="player">
        <button type="button" class="go" aria-label="play">▶</button>
        <audio preload="none" src="${src}"></audio>
        <span class="len">${fmtClock(dur)}</span>
      </div>
      <span class="who"><span class="spk ${who.klass || ""}">${who.name}</span></span>
      <span class="when">${fmtClock(c.start_sec)}</span>
      <div class="text-box">
        <button type="button" class="text-toggle" aria-label="показать текст">▾</button>
        <p class="text-preview">${escapeHtml(c.text || "—")}</p>
        <p class="text-full">${escapeHtml(c.text || "—")}</p>
      </div>
    </li>`;
  }).join("");

  body.querySelectorAll(".player").forEach((box) => {
    const audio = box.querySelector("audio");
    const btn = box.querySelector("button");
    btn.onclick = () => {
      document.querySelectorAll("audio").forEach((o) => { if (o !== audio) { o.pause(); o.closest(".player").querySelector("button").textContent = "▶"; } });
      if (audio.paused) { audio.play(); btn.textContent = "❚❚"; }
      else { audio.pause(); btn.textContent = "▶"; }
    };
    audio.addEventListener("ended", () => { btn.textContent = "▶"; });
  });
  body.querySelectorAll(".text-box").forEach((box) => {
    const btn = box.querySelector(".text-toggle");
    btn.onclick = () => {
      const open = box.classList.toggle("open");
      btn.textContent = open ? "▴" : "▾";
      btn.setAttribute("aria-label", open ? "скрыть текст" : "показать текст");
    };
  });

}

load();

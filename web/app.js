const FALLBACK_NAMES = {
  SPEAKER_00: { name: "SPEAKER_00", role: "", klass: "guest" },
  SPEAKER_01: { name: "SPEAKER_01", role: "", klass: "host" },
};

const fmtTime = (sec) => {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  const r = String(s % 60).padStart(2, "0");
  return `${m}:${r}`;
};

const fmtDur = (sec) => {
  if (sec >= 60) return `${Math.floor(sec / 60)} мин ${Math.round(sec % 60)} с`;
  return `${sec.toFixed(1)} с`;
};

let catalog = null;
let current = null;
let data = null;
let filter = "all";

const speakerMeta = (id) => {
  const fromCat = current && current.speakers && current.speakers[id];
  if (fromCat) return fromCat;
  return FALLBACK_NAMES[id] || { name: id, role: "", klass: "" };
};

async function load() {
  catalog = await (await fetch("./catalog.json")).json();
  const params = new URLSearchParams(location.search);
  const wanted = params.get("id") || (catalog.podcasts[0] && catalog.podcasts[0].id);
  current = catalog.podcasts.find((p) => p.id === wanted) || catalog.podcasts[0];
  data = await (await fetch(current.json)).json();
  renderNav();
  renderPage();
}

function renderNav() {
  const nav = document.getElementById("shows");
  if (!nav) return;
  nav.innerHTML = catalog.podcasts.map((p) => {
    const on = p.id === current.id ? " on" : "";
    return `<a class="show${on}" href="./?id=${encodeURIComponent(p.id)}">${p.title}</a>`;
  }).join("");
}

function renderPage() {
  document.title = `${data.title || current.title} — кыргызский датасет`;
  document.getElementById("title").textContent = data.title || current.title;
  const n = data.num_clips || (data.clips && data.clips.length) || 0;
  const speakers = data.num_speakers || (data.speakers && data.speakers.length) || 2;
  document.getElementById("stats").innerHTML = [
    [String(n), "клипов"],
    [String(speakers), "спикера"],
    [fmtDur(data.duration_sec || 0), "речи"],
    [(data.text_words || 0).toLocaleString("ru-RU"), "слов"],
  ].map(([num, l]) => `<div class="stat"><b>${num}</b><span>${l}</span></div>`).join("");

  const jsonLink = document.getElementById("dl-json");
  jsonLink.href = current.json;
  jsonLink.setAttribute("download", `${current.id}.json`);
  const zipLink = document.getElementById("dl-zip");
  if (current.folder_zip) {
    zipLink.href = current.folder_zip;
    zipLink.style.display = "";
  } else {
    zipLink.style.display = "none";
  }

  const yt = document.getElementById("yt");
  yt.href = current.youtube_url;
  yt.textContent = current.youtube_url.replace("https://", "");

  const filters = document.getElementById("filters");
  const ids = [...new Set((data.clips || []).map((c) => c.speaker))];
  filters.innerHTML = [
    `<button class="on" data-filter="all">Все</button>`,
    ...ids.map((id) => {
      const who = speakerMeta(id);
      const label = who.name && who.name !== id ? `${who.name}` : id;
      return `<button data-filter="${id}">${label}</button>`;
    }),
  ].join("");
  filters.querySelectorAll("[data-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      filter = btn.dataset.filter;
      filters.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("on", b === btn));
      renderClips();
    });
  });
  filter = "all";
  renderClips();
}

function renderClips() {
  const box = document.getElementById("clips");
  const prefix = current.audio_prefix || "./audio/";
  const clips = (data.clips || []).filter((c) => filter === "all" || c.speaker === filter);
  box.innerHTML = clips.map((c) => {
    const who = speakerMeta(c.speaker);
    const src = prefix + String(c.audio || c.filename).replace(/\.wav$/i, ".opus");
    return `
      <article class="clip" data-speaker="${c.speaker}">
        <div class="head">
          <div class="who ${who.klass || ""}">${c.id}. ${who.name}${who.role ? " · " + who.role : ""}</div>
          <div class="meta">${fmtTime(c.start_sec)}–${fmtTime(c.end_sec)} · ${fmtDur(c.duration_sec)} · ${c.text_words || 0} слов</div>
        </div>
        <p class="text">${c.text || ""}</p>
        <audio controls preload="none" src="${src}"></audio>
      </article>`;
  }).join("");
  box.querySelectorAll("audio").forEach((el) => {
    el.addEventListener("play", () => {
      box.querySelectorAll("audio").forEach((o) => { if (o !== el) o.pause(); });
    });
  });
}

load();

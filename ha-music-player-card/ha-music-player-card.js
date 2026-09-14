(function () {
  const API = "/api/ha_music_player";
  const STORE = "ha_music_player_state";
  const PLAYING = ["playing", "Playing", "播放", "播放中", "正在播放"];

  function hass() {
    const el = document.querySelector("home-assistant");
    return el && el.hass;
  }

  const I18N = {
    en: {
      browser: "This page",
      xiaoai: "Xiaoai",
      idle: "Not playing",
      pick: "Select a track",
      no_lyric: "No lyrics",
      list: "Queue",
      lyric: "Lyrics",
      search: "Search",
      playlist: "Playlists",
      all_list: "All",
      back: "Back",
      card_name: "Music Player",
      card_desc: "Local music / Xiaoai / speakers",
      xa_ph: "Song / artist, Enter to play",
    },
    zh: {
      browser: "本页",
      xiaoai: "小爱",
      idle: "未播放",
      pick: "选择歌曲",
      no_lyric: "暂无歌词",
      list: "列表",
      lyric: "歌词",
      search: "搜索",
      playlist: "歌单",
      all_list: "全部",
      back: "返回",
      card_name: "音乐播放器",
      card_desc: "本地音乐 / 小爱 / 音箱",
      xa_ph: "歌名/歌手，回车播放小爱曲库",
    },
  };

  function tr(key) {
    const h = hass();
    const l = ((h && ((h.locale && h.locale.language) || h.language)) || "").toLowerCase();
    return (l.startsWith("zh") ? I18N.zh : I18N.en)[key];
  }

  function authHeaders() {
    const h = hass();
    if (!h || !h.auth || !h.auth.data) return {};
    return { Authorization: "Bearer " + h.auth.data.access_token };
  }

  async function api(path, opt) {
    const headers = Object.assign({}, authHeaders(), (opt && opt.headers) || {});
    if (opt && opt.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const r = await fetch(API + path, Object.assign({}, opt || {}, { headers: headers }));
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  function loadStore() {
    try {
      return JSON.parse(localStorage.getItem(STORE) || "{}");
    } catch (e) {
      return {};
    }
  }

  function saveStore(s) {
    const cur = loadStore();
    localStorage.setItem(STORE, JSON.stringify(Object.assign(cur, s)));
  }

  function fmt(t) {
    t = Math.max(0, Math.floor(t || 0));
    const m = Math.floor(t / 60);
    const s = t % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function parseLrc(text) {
    const lines = [];
    if (!text) return lines;
    text.split("\n").forEach((line) => {
      const ts = [...line.matchAll(/\[(\d+):(\d+)(?:[.:](\d+))?\]/g)];
      const body = line.replace(/\[\d+:\d+(?:[.:]\d+)?\]/g, "").trim();
      if (!ts.length || !body) return;
      ts.forEach((m) => {
        let frac = 0;
        if (m[3]) frac = parseInt(m[3], 10) / (m[3].length === 2 ? 100 : 1000);
        lines.push({ time: parseInt(m[1], 10) * 60 + parseInt(m[2], 10) + frac, text: body });
      });
    });
    lines.sort((a, b) => a.time - b.time);
    return lines;
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const store = (window.__HMP = window.__HMP || {
    tracks: [],
    key: "",
    config: { enable_xiaoai: false, xiaomi_home: "", xiaomi_miot: "", media_players: [] },
    index: 0,
    playing: false,
    output: "browser",
    speaker: "",
    repeat: "all",
    shuffle: false,
    volume: 0.8,
    pos: 0,
    duration: 0,
    panel: "list",
    page: 0,
    folder: "",
    inList: false,
    filter: "",
    lyric: [],
    lyricRaw: "",
    views: [],
    roots: [],
    audio: null,
    timer: 0,
    loaded: false,
  });
  if (store.page == null) store.page = 0;
  if (store.folder == null) store.folder = "";
  if (store.inList == null) store.inList = false;
  if (!store.roots) store.roots = [];
  if (store.timer) {
    clearInterval(store.timer);
    store.timer = 0;
  }

  if (!store.audio) {
    store.audio = new Audio();
    store.audio.preload = "auto";
    store.audio.setAttribute("playsinline", "");
    store.audio.setAttribute("webkit-playsinline", "");
    const saved = loadStore();
    store.output = saved.output || "browser";
    store.speaker = saved.speaker || "";
    store.repeat = saved.repeat || "all";
    store.shuffle = !!saved.shuffle;
    store.volume = saved.volume != null ? saved.volume : 0.8;
    store.audio.volume = store.volume;
    store.audio.addEventListener("timeupdate", () => {
      if (store.output !== "browser") return;
      store.pos = store.audio.currentTime || 0;
      const d = store.audio.duration;
      if (d && isFinite(d)) store.duration = d;
      if (store._raf) return;
      store._raf = requestAnimationFrame(() => {
        store._raf = 0;
        patchProgress();
      });
    });
    store.audio.addEventListener("ended", () => onEnded());
    store.audio.addEventListener("play", () => {
      store.playing = true;
      patchChrome();
      queuePush();
    });
    store.audio.addEventListener("pause", () => {
      if (store._switching || store.output !== "browser") return;
      store.playing = false;
      patchChrome();
      queuePush();
    });
  }

  function emit() {
    store.views.forEach((fn) => {
      try {
        fn();
      } catch (e) {}
    });
    queuePush();
  }

  function addRoot(el) {
    if (el && store.roots.indexOf(el) < 0) store.roots.push(el);
  }

  function removeRoot(el) {
    store.roots = store.roots.filter((x) => x !== el);
  }

  function eachRoot(fn) {
    store.roots = store.roots.filter((el) => el && el.isConnected);
    store.roots.forEach((el) => {
      try {
        fn(el);
      } catch (e) {}
    });
  }

  function patchProgress() {
    const dur = store.duration || (track() && track().duration) || 0;
    const ratio = dur ? Math.min(1, store.pos / dur) : 0;
    const pct = ratio * 100 + "%";
    const t0 = fmt(store.pos);
    const t1 = fmt(dur);
    const li = lyricIndex();
    const lrcChanged = li !== store._li;
    eachRoot((root) => {
      const bar = root.querySelector(".hmp-prog>i");
      if (bar) bar.style.width = pct;
      const times = root.querySelectorAll(".hmp-time span");
      if (times[0]) times[0].textContent = t0;
      if (times[1]) times[1].textContent = t1;
      if (lrcChanged) {
        const prev = root.querySelector(".hmp-lrc p.on");
        if (prev) prev.classList.remove("on");
        if (li >= 0) {
          const p = root.querySelector(".hmp-lrc p:nth-child(" + (li + 1) + ")");
          if (p) p.classList.add("on");
        }
        if (store.page === 1) {
          const onEl = root.querySelector(".hmp-lrc p.on");
          const box = root.querySelector(".hmp-lrc");
          if (onEl && box) box.scrollTop = onEl.offsetTop - box.clientHeight / 2 + 20;
        }
      }
    });
    store._li = li;
  }

  function nowInfo() {
    if (store.output === "xiaoai" && store.xiaoaiNative) {
      const a = (speakerState() && speakerState().attributes) || {};
      if (a.media_title || store._xaQ) {
        return {
          title: a.media_title || store._xaQ,
          artist: a.media_artist || a.media_album_name || "",
          cover: a.entity_picture || "",
        };
      }
    }
    const t = track();
    return {
      title: t ? t.title : tr("idle"),
      artist: t ? t.artist || t.album || "" : tr("pick"),
      cover: coverUrl(t),
    };
  }

  function patchChrome() {
    const n = nowInfo();
    const playIco = store.playing ? icon("pause") : icon("play");
    eachRoot((root) => {
      const playBtn = root.querySelector(".hmp-btn.play");
      if (playBtn) playBtn.innerHTML = playIco;
      const bg = root.querySelector(".hmp-bg");
      if (bg) bg.style.backgroundImage = n.cover ? "url(" + n.cover + ")" : "";
      const name = root.querySelector(".hmp-name");
      if (name) name.textContent = n.title;
      const sub = root.querySelector(".hmp-artist");
      if (sub) sub.textContent = n.artist;
      const vol = root.querySelector(".hmp-vol");
      if (vol && document.activeElement !== vol) vol.value = String(store.volume);
      root.querySelectorAll(".hmp-item").forEach((el) => {
        el.classList.toggle("on", parseInt(el.getAttribute("data-i"), 10) === store.index);
      });
    });
    patchProgress();
  }

  function listItemsHtml() {
    const q = (store.filter || "").toLowerCase();
    return store.tracks
      .map((x, i) => ({ x, i }))
      .filter((o) => {
        if (store.folder && (o.x.folder || "") !== store.folder) return false;
        return !q || (o.x.title + o.x.artist + o.x.album + o.x.folder).toLowerCase().indexOf(q) >= 0;
      })
      .map((o) => {
        return (
          '<div class="hmp-item' +
          (o.i === store.index ? " on" : "") +
          '" data-act="play" data-i="' +
          o.i +
          '"><i>' +
          (o.i + 1) +
          "</i><div><div>" +
          esc(o.x.title) +
          '</div><div class="hmp-sub">' +
          esc(o.x.artist || o.x.folder) +
          "</div></div></div>"
        );
      })
      .join("");
  }

  function patchList() {
    const html = listItemsHtml();
    eachRoot((root) => {
      const list = root.querySelector(".hmp-list:not(.hmp-plist)");
      if (list) list.innerHTML = html;
    });
  }

  function stopSpeakerLoop() {
    if (store.timer) {
      clearInterval(store.timer);
      store.timer = 0;
    }
  }

  function speakerLoop() {
    if (store.output === "browser") {
      stopSpeakerLoop();
      return;
    }
    if (store.timer) return;
    store.timer = setInterval(() => {
      if (document.hidden || store.output === "browser") return;
      syncSpeaker();
    }, 1000);
  }

  function queuePush() {
    if (store._pushT) return;
    store._pushT = setTimeout(() => {
      store._pushT = 0;
      pushState();
    }, 300);
  }

  function pushState() {
    const t = track();
    api("/state", {
      method: "POST",
      body: JSON.stringify({
        index: store.index,
        track_id: t ? t.id : "",
        playing: store.playing,
        pos: store.pos,
        duration: store.duration,
        volume: store.volume,
        shuffle: store.shuffle,
        repeat: store.repeat,
        output: store.output,
      }),
    }).catch(function () {});
  }

  function listenCmd() {
    const h = hass();
    if (!h || !h.connection || store._cmdSub) return;
    store._cmdSub = true;
    h.connection.subscribeEvents((ev) => {
      const d = ev.data || {};
      const a = d.action;
      if (a === "play") playAt(d.index != null ? d.index : store.index);
      else if (a === "resume") {
        if (store.output === "browser") {
          if (store.audio.src) store.audio.play();
          else playAt(store.index);
        } else {
          store.playing = true;
          patchChrome();
          queuePush();
        }
      } else if (a === "pause") {
        store.audio.pause();
        store.playing = false;
        patchChrome();
        queuePush();
      } else if (a === "stop") {
        store.audio.pause();
        if (store.audio.src) store.audio.currentTime = 0;
        store.playing = false;
        store.pos = 0;
        patchChrome();
        queuePush();
      } else if (a === "next") next();
      else if (a === "prev") prev();
      else if (a === "seek" && d.pos != null) {
        const dur = store.duration || (track() && track().duration) || 0;
        if (dur) seek(d.pos / dur);
      } else if (a === "volume" && d.volume != null) setVolume(d.volume);
      else if (a === "shuffle") {
        store.shuffle = !!d.shuffle;
        saveStore({ shuffle: store.shuffle });
        emit();
      } else if (a === "repeat" && d.repeat) {
        store.repeat = d.repeat;
        saveStore({ repeat: store.repeat });
        emit();
      } else if (a === "source" && d.source) setOutput(d.source);
    }, "ha_music_player_cmd");
  }

  function on(fn) {
    store.views.push(fn);
    return () => {
      store.views = store.views.filter((x) => x !== fn);
    };
  }

  function track() {
    return store.tracks[store.index] || null;
  }

  function coverUrl(t) {
    if (!t || !t.has_cover) return "";
    return API + "/cover/" + t.id + "?key=" + encodeURIComponent(store.key);
  }

  function folderCover(folder) {
    const t = store.tracks.find((x) => (!folder || (x.folder || "") === folder) && x.has_cover);
    return coverUrl(t);
  }

  function albumCard(folder, name, on) {
    const src = folderCover(folder);
    return (
      '<div class="hmp-album' +
      (on ? " on" : "") +
      '" data-act="folder" data-f="' +
      esc(folder) +
      '"><b' +
      (src ? ' style="background-image:url(' + src + ')"' : "") +
      "></b><span>" +
      esc(name) +
      "</span></div>"
    );
  }

  function fileUrl(t) {
    return API + "/file/" + t.id + "?key=" + encodeURIComponent(store.key);
  }

  async function loadAll() {
    if (!hass()) return;
    try {
      const [lib, cfg] = await Promise.all([api("/library"), api("/config")]);
      const tracks = lib.tracks || [];
      const sig = tracks.length + ":" + ((tracks[0] && tracks[0].id) || "") + ":" + ((tracks[tracks.length - 1] && tracks[tracks.length - 1].id) || "");
      const cfgSig = JSON.stringify(cfg);
      store.tracks = tracks;
      store.key = lib.session_key || "";
      store.config = cfg;
      const saved = loadStore();
      if (saved.trackId) {
        const i = store.tracks.findIndex((x) => x.id === saved.trackId);
        if (i >= 0) store.index = i;
      }
      if (store.output === "xiaoai" && !cfg.enable_xiaoai) {
        store.output = "browser";
      } else if (store.output.indexOf("sp:") === 0 && (cfg.media_players || []).indexOf(store.output.slice(3)) < 0) {
        store.output = "browser";
      }
      const first = !store.loaded;
      store.loaded = true;
      if (first || sig !== store._sig || cfgSig !== store._cfgSig) {
        store._sig = sig;
        store._cfgSig = cfgSig;
        emit();
      }
      ensureLyric();
      speakerLoop();
    } catch (e) {}
  }

  function outputs() {
    const list = [{ id: "browser", name: tr("browser") }];
    (store.config.media_players || []).forEach((id) => {
      const st = hass() && hass().states[id];
      list.push({ id: "sp:" + id, name: (st && st.attributes.friendly_name) || id.replace("media_player.", "") });
    });
    if (store.config.enable_xiaoai && (store.config.xiaomi_home || store.config.xiaomi_miot)) {
      list.push({ id: "xiaoai", name: tr("xiaoai") });
    }
    return list;
  }

  function xiaoaiEntities() {
    return [store.config.xiaomi_miot, store.config.xiaomi_home].filter(Boolean);
  }

  function speakerId() {
    if (store.output === "xiaoai") return xiaoaiEntities()[0] || "";
    if (store.output.indexOf("sp:") === 0) return store.output.slice(3);
    return store.speaker;
  }

  function speakerState() {
    const h = hass();
    if (!h) return null;
    if (store.output === "xiaoai") {
      const ids = xiaoaiEntities();
      let fallback = null;
      let titled = null;
      for (let i = 0; i < ids.length; i++) {
        const st = h.states[ids[i]];
        if (!st) continue;
        if (!fallback) fallback = st;
        if (isPlayingState(st)) return st;
        if (!titled && st.attributes && st.attributes.media_title) titled = st;
      }
      return titled || fallback;
    }
    const id = speakerId();
    return id ? h.states[id] : null;
  }

  function isPlayingState(st) {
    return !!(st && PLAYING.indexOf(st.state) >= 0);
  }

  async function callMp(service, data) {
    const h = hass();
    if (!h) return;
    await h.callService("media_player", service, data);
  }

  async function callTargets(service, extra) {
    let ids = [];
    if (store.output === "xiaoai") ids = xiaoaiEntities();
    else if (speakerId()) ids = [speakerId()];
    for (let i = 0; i < ids.length; i++) {
      try {
        await callMp(service, Object.assign({ entity_id: ids[i] }, extra || {}));
        if (store.output === "xiaoai") return;
      } catch (e) {}
    }
  }

  async function playMediaUrl(url) {
    if (store.output === "xiaoai") {
      const ids = [store.config.xiaomi_miot, store.config.xiaomi_home].filter(Boolean);
      for (let i = 0; i < ids.length; i++) {
        try {
          await callMp("play_media", {
            entity_id: ids[i],
            media_content_id: url,
            media_content_type: "music",
          });
          return;
        } catch (e) {}
      }
      return;
    }
    const id = speakerId();
    if (!id) return;
    await callMp("play_media", {
      entity_id: id,
      media_content_id: url,
      media_content_type: "music",
    });
  }

  function lrcHtml() {
    const li = lyricIndex();
    if (store.lyric.length) {
      return store.lyric
        .map((line, i) => "<p class='" + (i === li ? "on" : "") + "'>" + esc(line.text) + "</p>")
        .join("");
    }
    if (store.lyricRaw) return "<p>" + esc(store.lyricRaw) + "</p>";
    return "<p>" + esc(tr("no_lyric")) + "</p>";
  }

  function paintLrc() {
    const html = lrcHtml();
    store._li = lyricIndex();
    eachRoot((root) => {
      const box = root.querySelector(".hmp-lrc");
      if (box) box.innerHTML = html;
    });
  }

  async function loadLyric(t) {
    const id = t ? t.id : "";
    store.lyric = [];
    store.lyricRaw = "";
    store._lyricId = id;
    if (!t) {
      paintLrc();
      return;
    }
    try {
      const j = await api("/lyric/" + t.id + "?key=" + encodeURIComponent(store.key));
      if (store._lyricId !== id) return;
      store.lyricRaw = j.lyric || "";
      store.lyric = parseLrc(store.lyricRaw);
    } catch (e) {}
    if (store._lyricId !== id) return;
    paintLrc();
  }

  async function ensureLyric() {
    const t = track();
    if (!t || store._lyricId === t.id) return;
    await loadLyric(t);
  }

  async function playAt(i) {
    if (!store.tracks.length) return;
    store.index = ((i % store.tracks.length) + store.tracks.length) % store.tracks.length;
    const t = track();
    saveStore({ trackId: t.id, output: store.output, speaker: store.speaker });
    store.xiaoaiNative = false;
    store._xaHold = true;
    store.playing = true;
    store.pos = 0;
    patchChrome();
    loadLyric(t);
    if (store.output === "browser") {
      store._switchN = (store._switchN || 0) + 1;
      const n = store._switchN;
      store._switching = true;
      store.audio.src = fileUrl(t);
      store.audio.volume = store.volume;
      store.audio.play().then(
        function () {
          if (n === store._switchN) store._switching = false;
        },
        function () {
          if (n !== store._switchN) return;
          store._switching = false;
          store.playing = false;
          patchChrome();
        }
      );
    } else {
      store._switching = true;
      store.audio.pause();
      store._switching = false;
      try {
        const j = await api("/play_url/" + t.id);
        await playMediaUrl(j.url);
      } catch (e) {}
    }
    queuePush();
  }

  async function playXiaoaiNative(q) {
    q = (q || "").trim();
    const cmd = !q ? "播放音乐" : /^播放/.test(q) ? q : "播放" + q;
    const ids = xiaoaiEntities();
    const h = hass();
    if (!h || !ids.length) return;
    store._xaQ = q;
    store.xiaoaiNative = true;
    store._xaHold = false;
    store.playing = true;
    store.audio.pause();
    patchChrome();
    for (let i = 0; i < ids.length; i++) {
      try {
        await h.callService("xiaomi_miot", "intelligent_speaker", {
          entity_id: ids[i],
          text: cmd,
          execute: true,
          silent: true,
        });
        return;
      } catch (e) {}
    }
    for (let i = 0; i < ids.length; i++) {
      try {
        await callMp("play_media", {
          entity_id: ids[i],
          media_content_id: q || "音乐",
          media_content_type: "music",
        });
        return;
      } catch (e) {}
    }
  }

  async function toggle() {
    if (store.output === "browser") {
      if (!track() || !store.audio.src) {
        playAt(store.index);
        return;
      }
      if (store.audio.paused) {
        store.playing = true;
        patchChrome();
        store.audio.play().catch(function () {
          store.playing = false;
          patchChrome();
        });
      } else store.audio.pause();
      return;
    }
    const st = speakerState();
    if (isPlayingState(st)) await callTargets("media_pause");
    else if (store.xiaoaiNative) await callTargets("media_play");
    else if (track()) await playAt(store.index);
    else await callTargets("media_play");
    patchChrome();
    queuePush();
  }

  function folderIndexes() {
    if (!store.folder) return store.tracks.map((_, i) => i);
    const ids = [];
    store.tracks.forEach((t, i) => {
      if ((t.folder || "") === store.folder) ids.push(i);
    });
    return ids.length ? ids : store.tracks.map((_, i) => i);
  }

  function nextIndex() {
    const ids = folderIndexes();
    if (!ids.length) return store.index + 1;
    if (store.shuffle) return ids[Math.floor(Math.random() * ids.length)];
    const p = ids.indexOf(store.index);
    if (p < 0) return ids[0];
    return ids[(p + 1) % ids.length];
  }

  function prevIndex() {
    const ids = folderIndexes();
    if (!ids.length) return store.index - 1;
    if (store.shuffle) return ids[Math.floor(Math.random() * ids.length)];
    const p = ids.indexOf(store.index);
    if (p < 0) return ids[0];
    return ids[(p - 1 + ids.length) % ids.length];
  }

  async function next() {
    if (store.output === "xiaoai" && store.xiaoaiNative) {
      await callTargets("media_next_track");
      return;
    }
    if (store.output !== "browser" && !track()) {
      await callTargets("media_next_track");
      return;
    }
    await playAt(nextIndex());
  }

  async function prev() {
    if (store.output === "xiaoai" && store.xiaoaiNative) {
      await callTargets("media_previous_track");
      return;
    }
    if (store.output !== "browser" && !track()) {
      await callTargets("media_previous_track");
      return;
    }
    await playAt(prevIndex());
  }

  async function onEnded() {
    if (store.repeat === "one") {
      await playAt(store.index);
      return;
    }
    if (store.repeat === "off") {
      const ids = folderIndexes();
      if (ids.indexOf(store.index) >= ids.length - 1) {
        store.playing = false;
        patchChrome();
        queuePush();
        return;
      }
    }
    await next();
  }

  async function seek(ratio) {
    const t = track();
    const dur = store.duration || (t && t.duration) || 0;
    if (!dur) return;
    const pos = dur * ratio;
    if (store.output === "browser") {
      store.audio.currentTime = pos;
      store.pos = pos;
    } else {
      try {
        await callTargets("media_seek", { seek_position: pos });
      } catch (e) {}
    }
    patchProgress();
    queuePush();
  }

  async function setVolume(v) {
    store.volume = v;
    store.audio.volume = v;
    saveStore({ volume: v });
    if (store.output !== "browser") {
      if (store._volT) clearTimeout(store._volT);
      store._volT = setTimeout(() => {
        store._volT = 0;
        callTargets("volume_set", { volume_level: store.volume });
      }, 180);
    }
  }

  function cycleRepeat() {
    store.repeat = store.repeat === "all" ? "one" : store.repeat === "one" ? "off" : "all";
    saveStore({ repeat: store.repeat });
    emit();
  }

  function toggleShuffle() {
    store.shuffle = !store.shuffle;
    saveStore({ shuffle: store.shuffle });
    emit();
  }

  function setOutput(id) {
    store.output = id;
    if (id.indexOf("sp:") === 0) store.speaker = id.slice(3);
    saveStore({ output: id, speaker: store.speaker });
    if (id !== "xiaoai") store.xiaoaiNative = false;
    speakerLoop();
    if (id === "browser" && track() && store.playing) playAt(store.index);
    emit();
  }

  function syncSpeaker() {
    if (store.output === "browser") return;
    const st = speakerState();
    if (!st) return;
    const playing = isPlayingState(st);
    const a = st.attributes || {};
    let pos = a.media_position || 0;
    if (a.media_position_updated_at && playing) {
      pos += (Date.now() - new Date(a.media_position_updated_at).getTime()) / 1000;
    }
    const duration = a.media_duration || (!store.xiaoaiNative && track() && track().duration) || 0;
    const volume = a.volume_level != null ? a.volume_level : store.volume;
    const title = a.media_title || "";
    const artist = a.media_artist || "";
    const prevTitle = store._xaTitle || "";
    if (store.output === "xiaoai") {
      if (store._xaHold) {
        if (title) store._xaHold = false;
      } else if (title && prevTitle && title !== prevTitle) {
        store.xiaoaiNative = true;
      } else if (playing && title && !prevTitle) {
        store.xiaoaiNative = true;
      }
    }
    const changed =
      playing !== store.playing ||
      Math.round(duration || 0) !== Math.round(store.duration || 0) ||
      title !== prevTitle ||
      artist !== (store._xaArtist || "");
    store.playing = playing;
    store.pos = pos;
    store.duration = duration;
    store.volume = volume;
    store._xaTitle = title;
    store._xaArtist = artist;
    if (changed) {
      patchChrome();
      queuePush();
    } else patchProgress();
  }

  function lyricIndex() {
    const t = store.pos;
    let idx = -1;
    for (let i = 0; i < store.lyric.length; i++) {
      if (store.lyric[i].time <= t) idx = i;
      else break;
    }
    return idx;
  }

  function skin() {
    return `
ha-card{display:block;width:100%;background:transparent;box-shadow:none;overflow:visible}
.hmp{--bg:rgba(26,26,30,.52);--fg:#f2f2f2;--mut:#9a9aa3;--acc:#3dd68c;--line:rgba(255,255,255,.12);font-family:system-ui,sans-serif;color:var(--fg);box-sizing:border-box;width:100%}
.hmp *{box-sizing:border-box}
.hmp-meta{flex:1;min-width:0}
.hmp-title{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hmp-sub{font-size:11px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hmp-btn{width:32px;height:32px;border:0;border-radius:50%;background:rgba(255,255,255,.1);color:var(--fg);cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none}
.hmp-btn.on{color:var(--acc)}
.hmp-panel{position:relative;width:100%;background:var(--bg);backdrop-filter:blur(22px) saturate(1.5);-webkit-backdrop-filter:blur(22px) saturate(1.5);border:1px solid rgba(255,255,255,.12);border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.28);overflow:hidden;display:flex;flex-direction:column}
.hmp-bg{position:absolute;inset:0;background:#2a2a30 center/cover no-repeat;pointer-events:none}
.hmp-bg:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.32) 0%,rgba(0,0,0,.78) 100%)}
.hmp-head{position:relative;z-index:1;display:flex;align-items:center;gap:8px;padding:10px 12px}
.hmp-head select{flex:1;background:rgba(255,255,255,.08);backdrop-filter:blur(16px) saturate(1.4);-webkit-backdrop-filter:blur(16px) saturate(1.4);color:#f2f2f2;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:6px 8px;font-size:12px}
.hmp-head select option{background:#fff;color:#111}
.hmp-body{padding:0 16px 12px}
.hmp-now{position:relative;min-height:380px;flex:1}
.hmp-now .hmp-body{flex:1;display:flex;flex-direction:column;justify-content:flex-end;padding-top:28px}
.hmp-name{text-align:center;font-size:16px;font-weight:600}
.hmp-artist{text-align:center;font-size:12px;color:var(--mut);margin:4px 0 12px}
.hmp-prog{height:4px;background:var(--line);border-radius:4px;cursor:pointer;position:relative}
.hmp-prog>i{display:block;height:100%;background:var(--acc);border-radius:4px;width:0}
.hmp-time{display:flex;justify-content:space-between;font-size:11px;color:var(--mut);margin:6px 0 10px}
.hmp-ctrls{display:flex;justify-content:center;align-items:center;gap:10px;margin-bottom:10px}
.hmp-ctrls .hmp-btn{width:36px;height:36px}
.hmp-ctrls .play{width:44px;height:44px;background:var(--acc);color:#111}
.hmp-vol{width:100%;accent-color:var(--acc)}
.hmp-tabs{display:flex;gap:8px;padding:0 16px 8px}
.hmp-tabs b{flex:1;text-align:center;font-size:12px;padding:6px;border-radius:8px;background:#2a2a30;cursor:pointer;font-weight:500}
.hmp-tabs b.on{background:var(--acc);color:#111}
.hmp-list{height:180px;overflow:auto;padding:0 8px 12px;touch-action:pan-y;overscroll-behavior:contain}
.hmp-item{display:flex;align-items:center;gap:8px;padding:8px;border-radius:8px;cursor:pointer;font-size:13px}
.hmp-item.on{background:rgba(255,255,255,.1);color:var(--acc)}
.hmp-item i{color:var(--mut);font-style:normal;width:22px;flex:none;font-size:12px}
.hmp-lrc{height:180px;overflow:auto;padding:8px 16px 16px;text-align:center;font-size:13px;line-height:1.8;touch-action:pan-y}
.hmp-lrc p{margin:0;color:var(--mut)}
.hmp-lrc p.on{color:var(--acc);font-size:15px}
.hmp-search{width:calc(100% - 16px);margin:0 8px 8px;background:rgba(255,255,255,.1);border:0;color:var(--fg);border-radius:8px;padding:6px 8px}
.hmp-search.hmp-xa{width:100%;margin:8px 0 0}
.hmp-card{background:transparent;border-radius:16px;overflow:hidden}
.hmp-swipe{position:relative;z-index:1;overflow:hidden;width:100%;touch-action:pan-y;flex:1}
.hmp-pages{display:flex;width:300%;transition:transform .3s cubic-bezier(.22,.61,.36,1);will-change:transform}
.hmp-page{width:33.333%;flex:none;min-width:0;display:flex;flex-direction:column;max-height:420px}
.hmp-page .hmp-lrc{flex:1;height:auto;min-height:240px;overflow:auto;font-size:15px;line-height:2}
.hmp-page .hmp-list{flex:1;height:auto;min-height:200px;overflow:auto}
.hmp-back{display:flex;align-items:center;gap:8px;padding:8px 16px;font-size:13px;cursor:pointer;color:var(--acc)}
.hmp-dots{position:relative;z-index:1;display:flex;justify-content:center;gap:8px;padding:4px 0 12px}
.hmp-dots i{width:7px;height:7px;border-radius:50%;background:#3a3a42;cursor:pointer;display:block}
.hmp-dots i.on{background:var(--acc)}
.hmp-plist-title{padding:8px 16px 4px;font-size:13px;color:var(--mut)}
.hmp-page .hmp-plist{flex:1;min-height:200px;overflow:auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:4px 12px 12px;height:auto}
.hmp-album{cursor:pointer;min-width:0}
.hmp-album b{display:block;aspect-ratio:1;border-radius:12px;background:#2a2a30 center/cover no-repeat;box-shadow:0 6px 16px rgba(0,0,0,.28)}
.hmp-album span{display:block;margin-top:6px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hmp-album.on b{box-shadow:0 0 0 2px var(--acc)}
`;
  }

  function icon(name) {
    const p = {
      play: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
      pause: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>',
      prev: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg>',
      next: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16 6h2v12h-2zM6 18l8.5-6L6 6z"/></svg>',
      list: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/></svg>',
      repeat: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z"/></svg>',
      shuffle: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M10.6 9.2 9.2 7.8 14 3h3v3l-6.4 3.2zM14 21l-1.4-1.4L17.2 15H14v-2h7v7h-2v-3.2zM4 5h2.8l12 12H21v2h-4.8L4 7V5zm0 12h2l3.2-3.2-1.4-1.4L4 16.2V17z"/></svg>',
    };
    return p[name] || "";
  }

  function renderInner(root) {
    const n = nowInfo();
    const dur = store.duration || (track() && track().duration) || 0;
    const ratio = dur ? Math.min(1, store.pos / dur) : 0;
    const outs = outputs();
    const playIco = store.playing ? icon("pause") : icon("play");
    const coverCss = n.cover ? "background-image:url(" + n.cover + ")" : "";

    const opts = outs
      .map((o) => '<option value="' + esc(o.id) + '"' + (store.output === o.id ? " selected" : "") + ">" + esc(o.name) + "</option>")
      .join("");
    const items = store.inList ? listItemsHtml() : "";
    const head =
      '<div class="hmp-head">' +
      (outs.length > 1 ? '<select data-act="output">' + opts + "</select>" : '<span style="flex:1"></span>') +
      '<button class="hmp-btn' +
      (store.repeat !== "off" ? " on" : "") +
      '" data-act="repeat" title="' +
      store.repeat +
      '">' +
      icon("repeat") +
      "</button>" +
      '<button class="hmp-btn' +
      (store.shuffle ? " on" : "") +
      '" data-act="shuffle">' +
      icon("shuffle") +
      "</button></div>";
    const xaBar =
      store.output === "xiaoai"
        ? '<input class="hmp-search hmp-xa" placeholder="' +
          esc(tr("xa_ph")) +
          '" value="' +
          esc(store._xaQ || "") +
          '" data-act="xiaoai">'
        : "";
    const playerBody =
      '<div class="hmp-body"><div class="hmp-name">' +
      esc(n.title) +
      '</div><div class="hmp-artist">' +
      esc(n.artist) +
      '</div><div class="hmp-prog" data-act="seek"><i style="width:' +
      ratio * 100 +
      '%"></i></div><div class="hmp-time"><span>' +
      fmt(store.pos) +
      "</span><span>" +
      fmt(dur) +
      '</span></div><div class="hmp-ctrls"><button class="hmp-btn" data-act="prev">' +
      icon("prev") +
      '</button><button class="hmp-btn play" data-act="toggle">' +
      playIco +
      '</button><button class="hmp-btn" data-act="next">' +
      icon("next") +
      '</button></div><input class="hmp-vol" type="range" min="0" max="1" step="0.01" value="' +
      store.volume +
      '" data-act="vol">' +
      xaBar +
      "</div>";

    let page3;
    if (store.inList) {
        page3 =
          '<div class="hmp-back" data-act="back">‹ ' +
          esc(store.folder || tr("all_list")) +
          '</div><input class="hmp-search" placeholder="' +
          esc(tr("search")) +
          '" value="' +
          esc(store.filter) +
          '" data-act="filter"><div class="hmp-list">' +
          items +
          "</div>";
      } else {
        const folders = [];
        store.tracks.forEach((x) => {
          const f = x.folder || "";
          if (f && folders.indexOf(f) < 0) folders.push(f);
        });
        folders.sort();
        const plist =
          albumCard("", tr("all_list"), false) + folders.map((f) => albumCard(f, f, false)).join("");
        page3 =
          '<div class="hmp-plist-title">' +
          esc(tr("playlist")) +
          '</div><div class="hmp-list hmp-plist">' +
          plist +
          "</div>";
      }
      const pg = store.page || 0;
      root.innerHTML =
        '<div class="hmp-panel hmp-card"><div class="hmp-bg" style="' +
        coverCss +
        '"></div>' +
        head +
        '<div class="hmp-swipe"><div class="hmp-pages" style="transform:translateX(-' +
        pg * 33.333 +
        '%)"><div class="hmp-page hmp-now">' +
        playerBody +
        '</div><div class="hmp-page"><div class="hmp-lrc">' +
        lrcHtml() +
        '</div></div><div class="hmp-page">' +
        page3 +
        "</div></div></div>" +
        '<div class="hmp-dots"><i class="' +
        (pg === 0 ? "on" : "") +
        '" data-act="page" data-p="0"></i><i class="' +
        (pg === 1 ? "on" : "") +
        '" data-act="page" data-p="1"></i><i class="' +
        (pg === 2 ? "on" : "") +
        '" data-act="page" data-p="2"></i></div></div>';

    const onEl = root.querySelector(".hmp-lrc p.on");
    const box = root.querySelector(".hmp-lrc");
    if (onEl && box && store.page === 1) {
      box.scrollTop = onEl.offsetTop - box.clientHeight / 2 + 20;
    }
    root.querySelectorAll(".hmp-list").forEach((el) => {
      const key = el.classList.contains("hmp-plist") ? "_plistScroll" : "_listScroll";
      el.scrollTop = store[key] || 0;
    });
    if (store._keepFilter) {
      const inp = root.querySelector(".hmp-search");
      if (inp) {
        inp.focus();
        const n = inp.value.length;
        inp.setSelectionRange(n, n);
      }
      store._keepFilter = false;
    }
  }

  function bind(root) {
    root.addEventListener("click", (e) => {
      const el = e.target.closest("[data-act]");
      if (!el) {
        store._swiped = false;
        return;
      }
      const act = el.getAttribute("data-act");
      if (store._swiped && act !== "toggle") {
        store._swiped = false;
        return;
      }
      store._swiped = false;
      if (act === "toggle") {
        e.stopPropagation();
        toggle();
      } else if (act === "prev") prev();
      else if (act === "next") next();
      else if (act === "repeat") cycleRepeat();
      else if (act === "shuffle") toggleShuffle();
      else if (act === "play") playAt(parseInt(el.getAttribute("data-i"), 10));
      else if (act === "panel") {
        store.panel = el.getAttribute("data-p");
        emit();
      } else if (act === "page") {
        goPage(root, parseInt(el.getAttribute("data-p"), 10) || 0);
      } else if (act === "folder") {
        store.folder = el.getAttribute("data-f") || "";
        store.inList = true;
        store.page = 2;
        store._listScroll = 0;
        emit();
      } else if (act === "back") {
        store.inList = false;
        store.filter = "";
        store._listScroll = 0;
        emit();
      } else if (act === "seek") {
        const r = el.getBoundingClientRect();
        seek((e.clientX - r.left) / r.width);
      }
    });
    root.addEventListener("change", (e) => {
      const el = e.target.closest("[data-act]");
      if (!el) return;
      const act = el.getAttribute("data-act");
      if (act === "output") setOutput(el.value);
      if (act === "vol") queuePush();
    });
    root.addEventListener("input", (e) => {
      const el = e.target.closest("[data-act]");
      if (!el) return;
      const act = el.getAttribute("data-act");
      if (act === "vol") setVolume(parseFloat(el.value));
      if (act === "filter") {
        store.filter = el.value;
        patchList();
      }
      if (act === "xiaoai") store._xaQ = el.value;
    });
    root.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const el = e.target.closest("[data-act=xiaoai]");
      if (!el) return;
      e.preventDefault();
      playXiaoaiNative(el.value);
    });
    function pageShift(page, dx) {
      return "translateX(calc(-" + page * 33.333 + "% + " + (dx || 0) + "px))";
    }
    function goPage(rootEl, page, dx) {
      store.page = Math.max(0, Math.min(2, page));
      const pages = rootEl.querySelector(".hmp-pages");
      if (pages) {
        pages.style.transition = dx ? "none" : "transform .3s cubic-bezier(.22,.61,.36,1)";
        pages.style.transform = pageShift(store.page, dx || 0);
      }
      rootEl.querySelectorAll(".hmp-dots i").forEach((d, i) => {
        d.classList.toggle("on", i === store.page);
      });
      if (!dx && store.page === 1) ensureLyric();
    }
    let sx = 0;
    let sy = 0;
    let axis = "";
    function endSwipe() {
      root._sw = false;
      root._swCap = false;
      axis = "";
    }
    root.addEventListener(
      "scroll",
      (e) => {
        const t = e.target;
        if (!t.classList) return;
        if (t.classList.contains("hmp-plist")) store._plistScroll = t.scrollTop;
        else if (t.classList.contains("hmp-list")) store._listScroll = t.scrollTop;
      },
      true
    );
    root.addEventListener(
      "wheel",
      (e) => {
        if (e.target.closest(".hmp-list,.hmp-lrc")) e.stopPropagation();
      },
      { passive: true }
    );
    root.addEventListener("pointerdown", (e) => {
      if (!e.target.closest(".hmp-swipe")) return;
      if (e.target.closest("button,select,input,[data-act=seek],[data-act=vol]")) return;
      sx = e.clientX;
      sy = e.clientY;
      axis = "";
      root._sw = true;
    });
    root.addEventListener(
      "pointermove",
      (e) => {
        if (!root._sw) return;
        const dx = e.clientX - sx;
        const dy = e.clientY - sy;
        if (!axis && (Math.abs(dx) > 6 || Math.abs(dy) > 6)) axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (axis === "y") {
          endSwipe();
          return;
        }
        if (axis !== "x") return;
        if (!root._swCap) {
          try {
            root.setPointerCapture(e.pointerId);
          } catch (err) {}
          root._swCap = true;
        }
        e.preventDefault();
        e.stopPropagation();
      },
      { passive: false }
    );
    root.addEventListener("pointerup", (e) => {
      if (!root._sw) return;
      const dx = e.clientX - sx;
      const wasX = axis === "x";
      endSwipe();
      if (!wasX) return;
      let next = store.page;
      if (dx < -50 && store.page < 2) next += 1;
      else if (dx > 50 && store.page > 0) next -= 1;
      if (next !== store.page) store._swiped = true;
      goPage(root, next);
    });
    root.addEventListener("pointercancel", endSwipe);
  }

  class HaMusicPlayerCard extends HTMLElement {
    setConfig(config) {
      this._config = config || {};
    }
    set hass(h) {
      this._hass = h;
      if (!this._inited) {
        this._inited = true;
        this.attachShadow({ mode: "open" });
        const style = document.createElement("style");
        style.textContent = skin() + ":host{display:block;width:100%}";
        const card = document.createElement("ha-card");
        this._box = document.createElement("div");
        this._box.className = "hmp";
        card.appendChild(this._box);
        this.shadowRoot.appendChild(style);
        this.shadowRoot.appendChild(card);
        addRoot(this._box);
        bind(this._box);
        this._off = on(() => renderInner(this._box));
        if (!store.loaded) loadAll();
        renderInner(this._box);
      } else if (store.output === "xiaoai") {
        const st = speakerState();
        const sig = st
          ? st.state + "|" + ((st.attributes && st.attributes.media_title) || "") + "|" + ((st.attributes && st.attributes.media_position_updated_at) || "")
          : "";
        if (sig !== store._xaSig) {
          store._xaSig = sig;
          syncSpeaker();
        }
      }
    }
    getCardSize() {
      return 8;
    }
    static getStubConfig() {
      return {};
    }
    disconnectedCallback() {
      if (this._off) this._off();
      removeRoot(this._box);
    }
  }

  function defineCard() {
    try {
      if (!customElements.get("ha-music-player-card")) {
        customElements.define("ha-music-player-card", HaMusicPlayerCard);
      }
    } catch (e) {}
  }
  defineCard();
  var _dn = 0;
  var _dt = setInterval(function () {
    defineCard();
    if (++_dn > 50) clearInterval(_dt);
  }, 100);

  function boot() {
    if (!document.body) {
      setTimeout(boot, 300);
      return;
    }
    if (!hass()) {
      setTimeout(boot, 400);
      return;
    }
    window.customCards = window.customCards || [];
    if (!window.customCards.find((c) => c.type === "ha-music-player-card")) {
      window.customCards.push({
        type: "ha-music-player-card",
        name: tr("card_name"),
        description: tr("card_desc"),
      });
    }
    listenCmd();
    if (!store.loaded) loadAll();
    speakerLoop();
    if (!store._watch) {
      store._watch = true;
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden && hass() && store.roots.length) loadAll();
      });
      setInterval(() => {
        if (!document.hidden && hass() && store.roots.length) loadAll();
      }, 60000);
    }
  }
  boot();
})();

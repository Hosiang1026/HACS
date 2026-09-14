window.customCards = window.customCards || [];
window.customCards.push({
  type: "chinese-festival-card",
  name: "中国节日日历",
  description: "Chinese festival month calendar",
  preview: true,
});

class ChineseFestivalCard extends HTMLElement {
  static getStubConfig() {
    return { entity: "date.chinese_festival_tap" };
  }

  setConfig(config) {
    this._config = { entity: "date.chinese_festival_tap", ...config };
  }

  getCardSize() {
    return 5;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._render();
  }

  _entityId() {
    return this._config?.entity || "date.chinese_festival_tap";
  }

  _state() {
    return this._hass?.states?.[this._entityId()];
  }

  _attrs() {
    return this._state()?.attributes || {};
  }

  _setDate(ymd) {
    if (!this._hass || !ymd) return;
    this._hass.callService("date", "set_value", {
      entity_id: this._entityId(),
      date: ymd,
    });
  }

  _shiftMonth(delta) {
    const attrs = this._attrs();
    const grid = attrs.month_grid || {};
    let y = Number(grid.year);
    let m = Number(grid.month);
    if (!y || !m) {
      const tap = String(attrs.selected_date || this._state()?.state || "").slice(0, 10);
      const p = tap.split("-").map(Number);
      y = p[0] || new Date().getFullYear();
      m = p[1] || new Date().getMonth() + 1;
    }
    m += delta;
    while (m < 1) {
      m += 12;
      y -= 1;
    }
    while (m > 12) {
      m -= 12;
      y += 1;
    }
    this._setDate(`${y}-${String(m).padStart(2, "0")}-01`);
  }

  _build() {
    this._built = true;
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      :host { display:block; }
      ha-card { padding:12px 14px 14px; }
      .head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
      .title { font-size:1.1em; font-weight:600; }
      .nav { display:flex; gap:6px; }
      button { border:none; background:var(--secondary-background-color); color:var(--primary-text-color); border-radius:6px; padding:4px 10px; cursor:pointer; }
      button:hover { background:var(--primary-color); color:var(--text-primary-color, #fff); }
      .week { display:grid; grid-template-columns:repeat(7,1fr); gap:2px; margin-bottom:4px; text-align:center; font-size:.75em; opacity:.7; }
      .grid { display:grid; grid-template-columns:repeat(7,1fr); gap:2px; }
      .cell { min-height:52px; border-radius:6px; padding:4px 2px; text-align:center; cursor:pointer; background:var(--secondary-background-color); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:1px; }
      .cell.out { opacity:.35; }
      .cell.selected { outline:2px solid var(--primary-color); background:color-mix(in srgb, var(--primary-color) 18%, transparent); }
      .cell.today .day { color:var(--primary-color); font-weight:700; }
      .day { font-size:.95em; line-height:1.1; }
      .sub { font-size:.65em; line-height:1.1; opacity:.8; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .sub.fest { color:var(--error-color, #c62828); opacity:1; }
      .info { margin-top:12px; display:grid; gap:6px; font-size:.9em; }
      .row { display:grid; grid-template-columns:2.2em 1fr; gap:8px; }
      .lab { opacity:.65; }
      .val { word-break:break-word; }
    `;
    this.shadowRoot.appendChild(style);
    const card = document.createElement("ha-card");
    this.shadowRoot.appendChild(card);
    this._card = card;
    card.addEventListener("click", (e) => {
      const prev = e.target.closest(".month-prev");
      const next = e.target.closest(".month-next");
      if (prev) {
        this._shiftMonth(-1);
        return;
      }
      if (next) {
        this._shiftMonth(1);
        return;
      }
      const cell = e.target.closest(".cell[data-date]");
      if (cell) this._setDate(cell.dataset.date);
    });
  }

  _festivalFor(i, grid) {
    return (
      grid.jieqi_text?.[i] ||
      grid.solar_festival?.[i] ||
      grid.lunar_festival?.[i] ||
      (grid.birthday_mark?.[i] || [])[0] ||
      ""
    );
  }

  _render() {
    if (!this._card || !this._hass) return;
    const attrs = this._attrs();
    const grid = attrs.month_grid || {};
    const dates = grid.dates || [];
    const inMonth = grid.in_month || [];
    const lunarText = grid.lunar_text || [];
    const selected = String(attrs.selected_date || this._state()?.state || "").slice(0, 10);
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const year = grid.year || selected.slice(0, 4);
    const month = grid.month || selected.slice(5, 7);
    const tapLunar = attrs.tap_lunar || grid.tap_lunar || {};
    const almanac = attrs.almanac || {};
    const tapIdx = dates.indexOf(selected);
    const festParts = [];
    if (tapIdx >= 0) {
      const f = this._festivalFor(tapIdx, grid);
      if (f) festParts.push(f);
      const marks = grid.birthday_mark?.[tapIdx] || [];
      for (const m of marks) if (m && !festParts.includes(m)) festParts.push(m);
      const hm = grid.holiday_mark?.[tapIdx];
      if (hm) festParts.push(hm);
    }
    const lunarLabel =
      tapLunar.full ||
      tapLunar.text ||
      [tapLunar.month, tapLunar.day].filter(Boolean).join("") ||
      (tapIdx >= 0 ? lunarText[tapIdx] : "") ||
      "-";
    const cells = dates
      .map((ymd, i) => {
        const d = Number(String(ymd).slice(8, 10));
        const fest = this._festivalFor(i, grid);
        const cls = [
          "cell",
          inMonth[i] === false ? "out" : "",
          ymd === selected ? "selected" : "",
          ymd === todayStr ? "today" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return `<div class="${cls}" data-date="${ymd}"><div class="day">${d}</div><div class="sub${fest ? " fest" : ""}">${fest || lunarText[i] || ""}</div></div>`;
      })
      .join("");
    this._card.innerHTML = `
      <div class="head">
        <div class="title">${year}年${Number(month)}月</div>
        <div class="nav">
          <button class="month-prev" type="button">‹</button>
          <button class="month-next" type="button">›</button>
        </div>
      </div>
      <div class="week"><div>一</div><div>二</div><div>三</div><div>四</div><div>五</div><div>六</div><div>日</div></div>
      <div class="grid">${cells || "<div>无月历数据</div>"}</div>
      <div class="info">
        <div class="row"><div class="lab">农历</div><div class="val">${lunarLabel}</div></div>
        <div class="row"><div class="lab">节日</div><div class="val">${festParts.join(" · ") || "无"}</div></div>
        <div class="row"><div class="lab">宜</div><div class="val">${almanac.suit || "-"}</div></div>
        <div class="row"><div class="lab">忌</div><div class="val">${almanac.avoid || "-"}</div></div>
      </div>
    `;
  }
}

customElements.define("chinese-festival-card", ChineseFestivalCard);

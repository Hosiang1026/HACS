(() => {
  const CARD_TYPE = "ha-msg-notify-card";
  const SPEED = 32;
  const HOLD = 2500;

  class HaMsgNotifyCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._hass = null;
      this._config = {};
      this._messages = [];
      this._idx = 0;
      this._key = "";
      this._timer = null;
      this._onEnd = null;
    }

    static getStubConfig(hass) {
      const entity =
        Object.keys(hass.states).find(
          (id) => id.startsWith("sensor.") && id.endsWith("_message_queue")
        ) || "sensor.message_queue";
      return { entity, height: 120 };
    }

    static async getConfigElement() {
      return document.createElement(`${CARD_TYPE}-editor`);
    }

    setConfig(config) {
      this._config = config || {};
      this._key = "";
      this._build();
      if (this._hass) this._sync();
    }

    set hass(hass) {
      this._hass = hass;
      this._sync();
    }

    getCardSize() {
      return Math.max(2, Math.ceil((Number(this._config.height) || 120) / 50));
    }

    getGridOptions() {
      const h = Number(this._config.height) || 120;
      const rows = Math.max(2, Math.ceil(h / 56));
      return { columns: 12, min_columns: 6, rows, min_rows: 2 };
    }

    connectedCallback() {
      if (this._hass) this._sync();
    }

    disconnectedCallback() {
      this._stop();
    }

    _height() {
      const h = Number(this._config.height);
      return h > 0 ? h : 120;
    }

    _build() {
      this._stop();
      const h = this._height();
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          ha-card {
            display: block;
            background: color-mix(in srgb, var(--ha-card-background, var(--card-background-color, #fff)) 38%, transparent);
            backdrop-filter: blur(18px) saturate(1.6);
            -webkit-backdrop-filter: blur(18px) saturate(1.6);
            border: 1px solid color-mix(in srgb, var(--primary-text-color, #fff) 14%, transparent);
            border-radius: var(--ha-card-border-radius, 12px);
            box-shadow: none;
            overflow: hidden;
          }
          .body {
            height: ${h}px;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            padding: 16px 12px 8px;
            overflow: hidden;
          }
          .vp {
            flex: 1;
            min-height: 0;
            overflow: hidden;
          }
          .msg {
            font-size: 15px;
            line-height: 1.45;
            color: #FFD740;
            text-shadow: 0 1px 3px rgba(0,0,0,0.5);
            white-space: pre-wrap;
            word-break: break-word;
            text-align: left;
            will-change: transform;
          }
          .src {
            flex-shrink: 0;
            text-align: right;
            font-size: 13px;
            margin-top: 6px;
            word-break: break-word;
            color: var(--secondary-text-color);
          }
        </style>
        <ha-card>
          <div class="body">
            <div class="vp"><div class="msg"></div></div>
            <div class="src"></div>
          </div>
        </ha-card>
      `;
    }

    _stop() {
      if (this._timer) {
        clearTimeout(this._timer);
        this._timer = null;
      }
      const msg = this.shadowRoot && this.shadowRoot.querySelector(".msg");
      if (msg && this._onEnd) {
        msg.removeEventListener("transitionend", this._onEnd);
        this._onEnd = null;
      }
    }

    _sync() {
      if (!this._hass || !this.shadowRoot.querySelector(".msg")) return;
      const entity = this._config.entity;
      if (!entity) return;
      const st = this._hass.states[entity];
      if (!st) return;
      let raw = st.attributes && st.attributes.messages;
      if (!Array.isArray(raw) || !raw.length) {
        const srcId =
          this._config.source_entity ||
          entity.replace(/_message_queue$/, "_current_source").replace(/_current_message$/, "_current_source");
        const srcSt = this._hass.states[srcId];
        raw = [
          {
            content: (st.attributes && st.attributes.message) || st.state || "",
            source: srcSt ? srcSt.state : "",
          },
        ];
      }
      const list = raw.map((m) =>
        m && typeof m === "object"
          ? { content: m.content || m.message || "", source: m.source || "" }
          : { content: String(m || ""), source: "" }
      );
      const key = JSON.stringify(list);
      if (key === this._key) return;
      const added = this._key && list.length > this._messages.length;
      this._key = key;
      this._messages = list;
      this._idx = added || !this._messages.length ? Math.max(0, this._messages.length - 1) : this._idx % Math.max(this._messages.length, 1);
      this._apply(true);
    }

    _apply(play) {
      this._stop();
      const item = this._messages[this._idx] || { content: "暂无消息", source: "" };
      const msg = this.shadowRoot.querySelector(".msg");
      const src = this.shadowRoot.querySelector(".src");
      msg.style.transition = "none";
      msg.style.transform = "translateY(0)";
      msg.textContent = item.content || "暂无消息";
      src.textContent = item.source || "";
      if (play) requestAnimationFrame(() => this._play());
    }

    _play() {
      const vp = this.shadowRoot.querySelector(".vp");
      const msg = this.shadowRoot.querySelector(".msg");
      if (!vp || !msg) return;
      const h = vp.clientHeight;
      const c = msg.scrollHeight;
      const end = Math.min(0, h - c);
      msg.style.transition = "none";
      msg.style.transform = `translateY(${h}px)`;
      const dur = Math.max(1.2, (h - end) / SPEED);
      const go = () => {
        msg.style.transition = `transform ${dur}s linear`;
        msg.style.transform = `translateY(${end}px)`;
      };
      requestAnimationFrame(() => requestAnimationFrame(go));
      this._onEnd = (ev) => {
        if (ev.propertyName && ev.propertyName !== "transform") return;
        msg.removeEventListener("transitionend", this._onEnd);
        this._onEnd = null;
        this._timer = setTimeout(() => this._next(), HOLD);
      };
      msg.addEventListener("transitionend", this._onEnd);
    }

    _next() {
      if (this._messages.length <= 1) return;
      this._idx = (this._idx + 1) % this._messages.length;
      this._apply(true);
    }
  }

  class HaMsgNotifyCardEditor extends HTMLElement {
    constructor() {
      super();
      this._hass = null;
      this._config = {};
      this._form = null;
    }

    setConfig(config) {
      this._config = { ...config };
      this._draw();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._form) this._form.hass = hass;
      else this._draw();
    }

    _draw() {
      if (!this._hass) return;
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.addEventListener("value-changed", (ev) => {
          this._config = ev.detail.value;
          this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
        });
        this._form.computeLabel = (schema) =>
          ({ entity: "消息队列", source_entity: "来源实体", height: "高度(px)" }[schema.name] || schema.name);
        this.appendChild(this._form);
      }
      this._form.hass = this._hass;
      this._form.data = this._config;
      this._form.schema = [
        { name: "entity", required: true, selector: { entity: { domain: "sensor" } } },
        { name: "source_entity", selector: { entity: { domain: "sensor" } } },
        { name: "height", selector: { number: { min: 60, max: 400, mode: "box", unit_of_measurement: "px" } } },
      ];
    }
  }

  if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, HaMsgNotifyCard);
  if (!customElements.get(`${CARD_TYPE}-editor`)) customElements.define(`${CARD_TYPE}-editor`, HaMsgNotifyCardEditor);

  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "通知消息轮播",
      description: "固定高度，消息自下而上滚动后轮播下一条",
      preview: true,
    });
  }

  const kick = (n) => {
    if (!n) return;
    if (n.localName === "hui-error-card") {
      n.dispatchEvent(new Event("ll-rebuild", { bubbles: true, composed: true }));
    }
    if (n.shadowRoot) kick(n.shadowRoot);
    if (n.querySelectorAll) n.querySelectorAll(":scope > *").forEach(kick);
  };
  customElements.whenDefined("home-assistant").then(() => kick(document.querySelector("home-assistant")));
})();

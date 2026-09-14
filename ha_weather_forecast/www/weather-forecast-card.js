const CARD_TYPE = "weather-forecast-card";
const DEFAULT_ICONS = "/ha_weather_forecast/frontend/icons/";

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: "天气预报卡片",
    description: "适配 ha_weather_forecast，带动画背景与预报",
    preview: true,
  });
}

function resolveLitElement() {
  const tags = [
    "ha-panel-lovelace",
    "hui-masonry-view",
    "hui-view",
    "home-assistant-main",
    "home-assistant",
  ];
  for (const tag of tags) {
    const el = customElements.get(tag);
    if (el) {
      return Object.getPrototypeOf(el);
    }
  }
  return window.LitElement || null;
}

function fireEvent(node, type, detail, options) {
  options = options || {};
  detail = detail === null || detail === undefined ? {} : detail;
  const event = new Event(type, {
    bubbles: options.bubbles === undefined ? true : options.bubbles,
    cancelable: Boolean(options.cancelable),
    composed: options.composed === undefined ? true : options.composed,
  });
  event.detail = detail;
  node.dispatchEvent(event);
  return event;
}

  function hasConfigOrEntityChanged(element, changedProps) {
  if (
    changedProps.has("_config") ||
    changedProps.has("_forecastDaily") ||
    changedProps.has("_forecastHourly") ||
    changedProps.has("showTarget")
  ) {
    return true;
  }
  if (!changedProps.has("hass")) {
    return false;
  }
  const oldHass = changedProps.get("hass");
  if (oldHass) {
    const idxId =
      String(element._config.entity || "").replace(/^weather\./, "sensor.") +
      "_indices";
    return (
      oldHass.states[element._config.entity] !==
        element.hass.states[element._config.entity] ||
      oldHass.states["sun.sun"] !== element.hass.states["sun.sun"] ||
      oldHass.states[idxId] !== element.hass.states[idxId]
    );
  }
  return true;
}

function isZh(lang) {
  return String(lang || "").toLowerCase().startsWith("zh");
}

function resolveHass(el) {
  return (
    el?.hass ||
    document.querySelector("home-assistant")?.hass ||
    null
  );
}

function indexItems(stateObj, hass) {
  const attrs = stateObj?.attributes || {};
  let raw = attrs.indices;
  if (
    !raw ||
    (typeof raw === "object" &&
      !Array.isArray(raw) &&
      !Object.keys(raw).length)
  ) {
    const slug = String(stateObj?.entity_id || "").replace(/^weather\./, "");
    const sensor = hass?.states?.[`sensor.${slug}_indices`];
    raw = sensor?.attributes?.indices;
  }
  if (Array.isArray(raw)) {
    return raw
      .map((item) => ({
        key: item.title || item.name || "",
        name: item.title_cn || item.name || item.title || "",
        level: item.brf || item.level || "",
        hint: item.txt || item.hint || "",
      }))
      .filter((item) => item.name || item.level);
  }
  if (!raw || typeof raw !== "object") {
    return [];
  }
  return Object.entries(raw)
    .map(([key, val]) => {
      if (val && typeof val === "object") {
        return {
          key,
          name: val.name || val.title_cn || val.title || key,
          level: val.level || val.brf || val.category || "",
          hint: val.hint || val.txt || val.des || "",
        };
      }
      return { key, name: key, level: val, hint: "" };
    })
    .filter((item) => item.name || item.level);
}

function indexIcon(key, name) {
  const k = String(key || "").toLowerCase();
  const n = String(name || "");
  const byKey = {
    ct: "mdi:tshirt-crew",
    uv: "mdi:white-balance-sunny",
    yd: "mdi:run",
    gm: "mdi:thermometer-plus",
    xc: "mdi:car-wash",
    tr: "mdi:wallet-travel",
    co: "mdi:emoticon-outline",
    comfort: "mdi:emoticon-outline",
    ls: "mdi:tumble-dryer",
    ag: "mdi:flower-pollen",
    ac: "mdi:air-conditioner",
    ys: "mdi:umbrella",
    gj: "mdi:shopping",
    dy: "mdi:fish",
    pk: "mdi:kite",
  };
  if (byKey[k]) return byKey[k];
  if (n.includes("紫外") || n.includes("防晒")) return "mdi:white-balance-sunny";
  if (n.includes("穿衣")) return "mdi:tshirt-crew";
  if (n.includes("运动")) return "mdi:run";
  if (n.includes("感冒")) return "mdi:thermometer-plus";
  if (n.includes("洗车")) return "mdi:car-wash";
  if (n.includes("旅游")) return "mdi:wallet-travel";
  if (n.includes("舒适")) return "mdi:emoticon-outline";
  if (n.includes("晾晒")) return "mdi:tumble-dryer";
  if (n.includes("过敏")) return "mdi:flower-pollen";
  if (n.includes("空调")) return "mdi:air-conditioner";
  if (n.includes("伞")) return "mdi:umbrella";
  if (n.includes("逛街") || n.includes("购物")) return "mdi:shopping";
  if (n.includes("钓鱼")) return "mdi:fish";
  if (n.includes("风筝")) return "mdi:kite";
  return "mdi:information-outline";
}

function injectIndices(el) {
  const root = el.shadowRoot || el.renderRoot;
  if (!root || !root.querySelector) return;
  const hass = resolveHass(el);
  const items = indexItems(el.stateObj, hass);
  let wrap = root.querySelector("#wf-indices");
  if (!items.length) {
    if (wrap) wrap.remove();
    return;
  }
  if (!root.querySelector("#wf-indices-style")) {
    const style = document.createElement("style");
    style.id = "wf-indices-style";
    style.textContent =
      "#wf-indices{margin-top:16px;padding-top:8px;border-top:1px solid var(--divider-color)}" +
      ".wf-idx-title{font-size:1.1em;margin-bottom:8px}" +
      ".wf-idx{display:flex;align-items:center;gap:8px;padding:6px 0;line-height:1.4}" +
      ".wf-idx ha-icon{color:var(--paper-item-icon-color,var(--secondary-text-color));flex-shrink:0}" +
      ".wf-idx-text{flex:1;min-width:0}";
    root.appendChild(style);
  }
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = "wf-indices";
    const attr = root.querySelector(".attribution");
    if (attr && attr.parentNode) {
      attr.parentNode.insertBefore(wrap, attr);
    } else {
      root.appendChild(wrap);
    }
  }
  const title = isZh(hass?.language) ? "生活指数" : "Life indices";
  wrap.replaceChildren();
  const head = document.createElement("div");
  head.className = "wf-idx-title";
  head.textContent = title;
  wrap.appendChild(head);
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "wf-idx";
    const icon = document.createElement("ha-icon");
    icon.icon = indexIcon(item.key, item.name);
    const text = document.createElement("div");
    text.className = "wf-idx-text";
    const name = item.name || "";
    const level = item.level || item.hint || "";
    text.textContent =
      name && level ? `${name}：${level}` : name || level;
    row.append(icon, text);
    wrap.appendChild(row);
  }
}

function patchMoreInfoWeather(ctor) {
  if (!ctor || ctor.prototype._wfIdxPatch) return;
  ctor.prototype._wfIdxPatch = true;
  const orig = ctor.prototype.updated;
  ctor.prototype.updated = function (changed) {
    if (typeof orig === "function") orig.call(this, changed);
    injectIndices(this);
  };
}

function installMoreInfoPatch() {
  if (window.__wfIdxMoreInfoPatch) return;
  window.__wfIdxMoreInfoPatch = true;
  const existing = customElements.get("more-info-weather");
  if (existing) patchMoreInfoWeather(existing);
  const prev = customElements.define.bind(customElements);
  customElements.define = function (name, ctor, options) {
    if (name === "more-info-weather") patchMoreInfoWeather(ctor);
    return prev(name, ctor, options);
  };
}

installMoreInfoPatch();

function effectKind(condition, sun) {
  const c = String(condition || "").toLowerCase();
  const night = sun && sun.state === "below_horizon";
  if (c === "pouring") return "pouring";
  if (c === "hail") return "hail";
  if (c === "lightning-rainy") return "thunder";
  if (c === "lightning") return "lightning";
  if (c === "snowy-rainy") return "sleet";
  if (c === "rainy") return "rainy";
  if (c === "snowy") return "snowy";
  if (c === "fog") return "fog";
  if (c === "dust") return "dust";
  if (c === "windy-variant") return night ? "windy-variant-night" : "windy-variant";
  if (c === "windy") return "windy";
  if (c === "cloudy") return "cloudy";
  if (c === "partlycloudy") return night ? "partlycloudy-night" : "partlycloudy";
  if (c === "clear-night" || ((c === "sunny" || c === "clear") && night)) {
    return "clear-night";
  }
  if (c === "sunny" || c === "clear") return "sunny";
  if (c === "exceptional") return "exceptional";
  return night ? "clear-night" : "cloudy";
}

const weatherIconsDay = {
  clear: "day",
  "clear-night": "night",
  cloudy: "cloudy",
  fog: "cloudy",
  hail: "rainy-7",
  lightning: "thunder",
  "lightning-rainy": "thunder",
  partlycloudy: "cloudy-day-3",
  pouring: "rainy-6",
  rainy: "rainy-5",
  snowy: "snowy-6",
  "snowy-rainy": "rainy-7",
  sunny: "day",
  windy: "cloudy",
  "windy-variant": "cloudy-day-3",
  dust: "cloudy",
  exceptional: "cloudy",
};

const weatherIconsNight = {
  ...weatherIconsDay,
  clear: "night",
  sunny: "night",
  partlycloudy: "cloudy-night-3",
  "windy-variant": "cloudy-night-3",
};

  const colorfulIconsDay = {
  clear: "CLEAR_DAY",
  "clear-night": "CLEAR_NIGHT",
  cloudy: "CLOUDY",
  fog: "FOG",
  hail: "MODERATE_RAIN",
  lightning: "STORM_RAIN",
  "lightning-rainy": "STORM_RAIN",
  partlycloudy: "PARTLY_CLOUDY_DAY",
  pouring: "HEAVY_RAIN",
  rainy: "MODERATE_RAIN",
  snowy: "MODERATE_SNOW",
  "snowy-rainy": "LIGHT_SNOW",
  sunny: "CLEAR_DAY",
  windy: "WIND",
  "windy-variant": "WIND",
  dust: "DUST",
  exceptional: "CLOUDY",
};

const colorfulIconsNight = {
  ...colorfulIconsDay,
  clear: "CLEAR_NIGHT",
  sunny: "CLEAR_NIGHT",
  partlycloudy: "PARTLY_CLOUDY_NIGHT",
};

const windDirectionsEn = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW", "N",
];

const windDirectionsZh = [
  "北", "北东北", "东北", "东北东", "东", "东南东", "东南", "南东南",
  "南", "南西南", "西南", "西南西", "西", "西北西", "西北", "北西北", "北",
];

function defineWeatherForecastCard(LitElement) {
  const html = LitElement.prototype.html;
  const css = LitElement.prototype.css;

  class WeatherForecastCard extends LitElement {
  static get properties() {
    return {
      _config: {},
      _forecastDaily: {},
      _forecastHourly: {},
      hass: {},
      showTarget: { type: Number },
    };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "weather" } },
        },
        { name: "name", selector: { text: {} } },
        { name: "icons", selector: { text: {} } },
        { name: "current", default: true, selector: { boolean: {} } },
        { name: "details", default: true, selector: { boolean: {} } },
        { name: "forecast", default: true, selector: { boolean: {} } },
        { name: "forecast_daily", default: true, selector: { boolean: {} } },
        { name: "forecast_hourly", default: true, selector: { boolean: {} } },
        {
          name: "number_of_forecasts",
          default: 5,
          selector: { number: { min: 1, max: 15, mode: "box" } },
        },
        {
          name: "hide_precipitation",
          default: false,
          selector: { boolean: {} },
        },
        {
          name: "effects",
          default: true,
          selector: { boolean: {} },
        },
      ],
    };
  }

  static async getConfigElement() {
    await import("./weather-forecast-card-editor.js");
    return document.createElement("weather-forecast-card-editor");
  }

  static getStubConfig(hass, unusedEntities, allEntities) {
    let entity = unusedEntities.find((eid) => eid.split(".")[0] === "weather");
    if (!entity) {
      entity = allEntities.find((eid) => eid.split(".")[0] === "weather");
    }
    return {
      entity,
      forecast_daily: true,
      forecast_hourly: true,
      number_of_forecasts: 5,
    };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("请设置天气实体");
    }
    this._config = {
      ...config,
      forecast_daily: config.forecast_daily !== false,
      forecast_hourly: config.forecast_hourly !== false,
    };
    this.showTarget = 0;
    this.tempMAX = null;
    this.tempMIN = null;
    this.tempCOLOR = [];
  }

  _needForecastSubscription() {
    return (
      this._config &&
      this._config.forecast !== false &&
      (this._config.forecast_daily !== false ||
        this._config.forecast_hourly !== false)
    );
  }

  _wantedTypes() {
    const types = [];
    if (this._config.forecast_daily !== false) types.push("daily");
    if (this._config.forecast_hourly !== false) types.push("hourly");
    return types;
  }

  _unsubscribeForecastEvents() {
    const subs = this._subscribedList || [];
    this._subscribedList = [];
    this._subscribed = undefined;
    for (const sub of subs) {
      Promise.resolve(sub)
        .then((unsub) => {
          if (typeof unsub === "function") unsub();
        })
        .catch(() => {});
    }
  }

  async _subscribeForecastEvents() {
    this._unsubscribeForecastEvents();
    if (
      !this.isConnected ||
      !this.hass ||
      !this._config ||
      !this._needForecastSubscription()
    ) {
      return;
    }
    const entity_id = this._config.entity;
    const types = this._wantedTypes();
    const list = [];

    for (const type of types) {
      const applyEvent = (event) => {
        if (event && Array.isArray(event.forecast) && event.forecast.length) {
          if (type === "hourly") {
            this._forecastHourly = { forecast: event.forecast, type: "hourly" };
            this._computeHourlyColors(event.forecast);
          } else {
            this._forecastDaily = { forecast: event.forecast, type: "daily" };
          }
          this.requestUpdate();
          this.updateComplete.then(() => this._adjustScrollPosition());
        }
      };
      try {
        list.push(
          await this.hass.connection.subscribeMessage(applyEvent, {
            type: "weather/subscribe_forecast",
            forecast_type: type,
            entity_id,
          })
        );
      } catch (e) {}
    }
    this._subscribedList = list;
    this._subscribed = list.length ? list[0] : undefined;

    await this._fetchForecastOnce(entity_id);
    if (!this._hasForecast()) {
      window.setTimeout(() => {
        if (this.isConnected && !this._hasForecast()) {
          this._fetchForecastOnce(this._config.entity);
        }
      }, 2000);
    }
  }

  _hasForecastType(type) {
    const ev = type === "hourly" ? this._forecastHourly : this._forecastDaily;
    return !!(ev && Array.isArray(ev.forecast) && ev.forecast.length);
  }

  _hasForecast() {
    const types = this._wantedTypes();
    if (!types.length) return true;
    return types.every((t) => this._hasForecastType(t));
  }

  async _fetchForecastOnce(entity_id) {
    for (const type of this._wantedTypes()) {
      if (this._hasForecastType(type)) continue;
      const forecast = await this._callGetForecasts(entity_id, type);
      if (Array.isArray(forecast) && forecast.length) {
        if (type === "hourly") {
          this._forecastHourly = { forecast, type: "hourly" };
          this._computeHourlyColors(forecast);
        } else {
          this._forecastDaily = { forecast, type: "daily" };
        }
        this.requestUpdate();
        this.updateComplete.then(() => this._adjustScrollPosition());
      }
    }
  }

  async _callGetForecasts(entity_id, type) {
    const pick = (obj) => {
      if (!obj || typeof obj !== "object") return null;
      const direct = obj?.[entity_id]?.forecast;
      if (Array.isArray(direct)) return direct;
      const nested = obj?.response?.[entity_id]?.forecast;
      if (Array.isArray(nested)) return nested;
      for (const v of Object.values(obj)) {
        if (v && Array.isArray(v.forecast) && v.forecast.length) {
          return v.forecast;
        }
        if (v && typeof v === "object") {
          for (const vv of Object.values(v)) {
            if (vv && Array.isArray(vv.forecast) && vv.forecast.length) {
              return vv.forecast;
            }
          }
        }
      }
      return null;
    };

    try {
      if (typeof this.hass.callService === "function") {
        const result = await this.hass.callService(
          "weather",
          "get_forecasts",
          { type },
          { entity_id: [entity_id] },
          true,
          true
        );
        const fromCall = pick(result) || pick(result?.response);
        if (fromCall) return fromCall;
      }
    } catch (e) {}

    try {
      const resp = await this.hass.connection.sendMessagePromise({
        type: "call_service",
        domain: "weather",
        service: "get_forecasts",
        target: { entity_id: [entity_id] },
        service_data: { type },
        return_response: true,
      });
      return pick(resp) || pick(resp?.result) || null;
    } catch (e) {
      return null;
    }
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.hasUpdated && this._config && this.hass && !this._subscribing) {
      this._subscribing = true;
      this._subscribeForecastEvents().finally(() => {
        this._subscribing = false;
      });
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribeForecastEvents();
  }

  shouldUpdate(changedProps) {
    return hasConfigOrEntityChanged(this, changedProps);
  }

  updated(changedProps) {
    if (!this.hass || !this._config) {
      return;
    }
    if (changedProps.has("_config") || (!this._subscribed && !this._subscribing)) {
      this._subscribing = true;
      this._subscribeForecastEvents().finally(() => {
        this._subscribing = false;
      });
      return;
    }
    // 实体刷新后若仍无预报，再拉一次
    if (changedProps.has("hass") && this._config.forecast !== false && !this._hasForecast()) {
      this._fetchForecastOnce(this._config.entity);
    }
  }

  render() {
    if (!this._config || !this.hass) {
      return html``;
    }

    this.numberElements = 0;
    const lang = this.hass.selectedLanguage || this.hass.language;
    const stateObj = this.hass.states[this._config.entity];

    if (!stateObj) {
      return html`
        <style>
          .not-found {
            flex: 1;
            background-color: var(--warning-color);
            padding: 8px;
          }
        </style>
        <ha-card>
          <div class="not-found">
            Entity not available: ${this._config.entity}
          </div>
        </ha-card>
      `;
    }

    const kind = effectKind(
      stateObj.state,
      this.hass.states["sun.sun"]
    );

    return html`
      <ha-card class="weather-fx weather-fx--${kind}" @click="${this._handleClick}">
        ${this._config.effects !== false ? this.renderEffects(kind) : ""}
        <div class="card-content">
          ${this._config.current !== false ? this.renderCurrent(stateObj) : ""}
          ${this._config.details !== false
            ? this.renderDetails(stateObj, lang)
            : ""}
          ${this._config.forecast !== false
            ? this.renderForecasts(stateObj, lang)
            : ""}
        </div>
      </ha-card>
    `;
  }

  _forecastPayload(type, stateObj) {
    if (type === "hourly") {
      const ev = this._forecastHourly;
      if (ev && Array.isArray(ev.forecast) && ev.forecast.length) {
        return ev;
      }
      return null;
    }
    const ev = this._forecastDaily;
    if (ev && Array.isArray(ev.forecast) && ev.forecast.length) {
      return ev;
    }
    if (type === "daily") {
      const legacy = stateObj?.attributes?.forecast;
      if (Array.isArray(legacy) && legacy.length) {
        return { forecast: legacy, type: "daily" };
      }
    }
    return null;
  }

  renderForecasts(stateObj, lang) {
    const parts = [];
    if (this._config.forecast_daily !== false) {
      const dailyPayload = this._forecastPayload("daily", stateObj);
      if (dailyPayload) {
        parts.push(this.renderDailyForecast(dailyPayload, lang));
      }
    }
    if (this._config.forecast_hourly !== false) {
      const hourlyPayload = this._forecastPayload("hourly", stateObj);
      if (hourlyPayload) {
        parts.push(this.renderHourlyForecast(hourlyPayload, lang));
      }
    }
    return parts;
  }

  renderEffects(kind) {
    const n = (count) => Array.from({ length: count }, (_, i) => i);
    const rainStyle = (i, base, step, spread) =>
      `--i:${i};--dur:${base + (i % 7) * step}s;--x:${(i * spread) % 98}%;--len:${14 + (i % 5) * 4}px`;
    const snowStyle = (i, base) =>
      `--i:${i};--dur:${base + (i % 6) * 0.3}s;--x:${(i * 3.5) % 96}%;--sz:${5 + (i % 4) * 2}px;--drift:${-16 + (i % 7) * 6}px`;
    return html`
      <div class="fx" aria-hidden="true">
        <div class="fx-tint"></div>
        ${kind === "sunny"
          ? html`
              <div class="fx-rays">
                ${n(24).map(
                  (i) =>
                    html`<i
                      class="fx-beam"
                      style="--a:${i * 15}deg;--w:${0.7 + (i % 3) * 0.25}em;--d:${-i * 0.12}s"
                    ></i>`
                )}
              </div>
              <div class="fx-sun"></div>
              ${n(16).map(
                (i) =>
                  html`<i
                    class="fx-spark"
                    style="--i:${i};--x:${44 + ((i * 17) % 50)}%;--y:${8 + ((i * 23) % 55)}%"
                  ></i>`
              )}
            `
          : ""}
        ${kind === "clear-night"
          ? html`
              <div class="fx-moon"></div>
              ${n(28).map(
                (i) =>
                  html`<i
                    class="fx-star"
                    style="--i:${i};--x:${4 + ((i * 37) % 90)}%;--y:${4 + ((i * 53) % 75)}%"
                  ></i>`
              )}
            `
          : ""}
        ${kind === "partlycloudy"
          ? html`
              <div class="fx-rays fx-rays--soft">
                ${n(4).map(
                  (i) =>
                    html`<i
                      class="fx-beam"
                      style="--a:${32 + i * 9}deg;--w:${1.3 + (i % 2) * 0.6}em;--d:${-i * 0.5}s"
                    ></i>`
                )}
              </div>
              <div class="fx-sun fx-sun--soft"></div>
              ${n(8).map(
                (i) =>
                  html`<i
                    class="fx-spark"
                    style="--i:${i};--x:${52 + ((i * 19) % 40)}%;--y:${12 + ((i * 21) % 40)}%"
                  ></i>`
              )}
            `
          : ""}
        ${kind === "partlycloudy-night"
          ? html`<div class="fx-moon fx-moon--soft"></div>${n(14).map(
              (i) =>
                html`<i
                  class="fx-star"
                  style="--i:${i};--x:${8 + ((i * 41) % 84)}%;--y:${6 + ((i * 29) % 50)}%"
                ></i>`
            )}`
          : ""}
        ${kind === "cloudy"
          ? html`
              <div class="fx-shade"></div>
              <div class="fx-shade fx-shade--2"></div>
              <div class="fx-shade fx-shade--3"></div>
              <div class="fx-mist fx-mist--cloudy"></div>
              <div class="fx-mist fx-mist--cloudy fx-mist--2"></div>
              ${n(18).map(
                (i) =>
                  html`<i
                    class="fx-haze"
                    style="--i:${i};--x:${(i * 5.3) % 96}%;--y:${8 + ((i * 17) % 70)}%;--dur:${3.5 + (i % 5) * 0.5}s;--sz:${3 + (i % 3) * 2}px"
                  ></i>`
              )}
            `
          : ""}
        ${kind === "fog"
          ? html`
              <div class="fx-mist"></div>
              <div class="fx-mist fx-mist--2"></div>
              <div class="fx-mist fx-mist--3"></div>
            `
          : ""}
        ${kind === "dust"
          ? n(36).map(
              (i) =>
                html`<i
                  class="fx-dust"
                  style="--i:${i};--x:${(i * 2.7) % 96}%;--dur:${3 + (i % 5) * 0.5}s;--sz:${3 + (i % 4) * 2}px"
                ></i>`
            )
          : ""}
        ${kind === "windy"
          ? n(18).map((i) => html`<i class="fx-gust fx-gust--strong" style="--i:${i}"></i>`)
          : ""}
        ${kind === "windy-variant"
          ? html`
              <div class="fx-rays fx-rays--soft">
                ${n(4).map(
                  (i) =>
                    html`<i
                      class="fx-beam"
                      style="--a:${32 + i * 9}deg;--w:${1.3 + (i % 2) * 0.6}em;--d:${-i * 0.5}s"
                    ></i>`
                )}
              </div>
              <div class="fx-sun fx-sun--soft"></div>
              ${n(14).map((i) => html`<i class="fx-gust" style="--i:${i}"></i>`)}
            `
          : ""}
        ${kind === "windy-variant-night"
          ? html`
              <div class="fx-moon fx-moon--soft"></div>
              ${n(14).map((i) => html`<i class="fx-gust" style="--i:${i}"></i>`)}
            `
          : ""}
        ${kind === "rainy"
          ? n(36).map(
              (i) =>
                html`<i class="fx-drop fx-drop--light" style="${rainStyle(i, 0.65, 0.08, 2.7)}"></i>`
            )
          : ""}
        ${kind === "pouring"
          ? n(72).map(
              (i) =>
                html`<i class="fx-drop fx-drop--heavy" style="${rainStyle(i, 0.28, 0.04, 1.35)}"></i>`
            )
          : ""}
        ${kind === "hail"
          ? html`
              ${n(24).map(
                (i) =>
                  html`<i class="fx-drop fx-drop--light" style="${rainStyle(i, 0.55, 0.07, 4)}"></i>`
              )}
              ${n(36).map(
                (i) =>
                  html`<i
                    class="fx-hail"
                    style="--i:${i};--dur:${0.4 + (i % 5) * 0.06}s;--x:${(i * 2.7) % 97}%;--sz:${6 + (i % 3) * 3}px"
                  ></i>`
              )}
            `
          : ""}
        ${kind === "lightning"
          ? html`
              <div class="fx-flash"></div>
              <div class="fx-bolt"></div>
              <div class="fx-bolt fx-bolt--2"></div>
              <div class="fx-bolt fx-bolt--3"></div>
            `
          : ""}
        ${kind === "thunder"
          ? html`
              ${n(56).map(
                (i) =>
                  html`<i class="fx-drop fx-drop--heavy" style="${rainStyle(i, 0.32, 0.05, 1.7)}"></i>`
              )}
              <div class="fx-flash"></div>
              <div class="fx-bolt"></div>
              <div class="fx-bolt fx-bolt--2"></div>
            `
          : ""}
        ${kind === "snowy"
          ? n(48).map((i) => html`<i class="fx-flake" style="${snowStyle(i, 1.8)}"></i>`)
          : ""}
        ${kind === "sleet"
          ? html`
              ${n(28).map(
                (i) =>
                  html`<i class="fx-drop fx-drop--light" style="${rainStyle(i, 0.55, 0.07, 3.4)}"></i>`
              )}
              ${n(28).map((i) => html`<i class="fx-flake" style="${snowStyle(i, 2)}"></i>`)}
            `
          : ""}
        ${kind === "exceptional"
          ? html`<div class="fx-warn"></div>`
          : ""}
      </div>
    `;
  }

  renderCurrent(stateObj) {
    this.numberElements++;
    const temp = stateObj.attributes.temperature;
    const unit = this.getUnit("temperature");
    const title =
      this._config.name ||
      stateObj.attributes.friendly_name ||
      this._config.entity.replace(/^weather\./, "");
    let conditionText = stateObj.state;
    try {
      if (this.hass.formatEntityState) {
        conditionText = this.hass.formatEntityState(stateObj);
      }
    } catch (e) {}
    const iconUrl = this.getWeatherIcon(
      stateObj.state.toLowerCase(),
      this.hass.states["sun.sun"]
    );
    const secondary = this._config.secondary_info_attribute;
    const secondaryVal =
      secondary && stateObj.attributes[secondary] != null
        ? stateObj.attributes[secondary]
        : null;
    let secondaryLabel = secondary || "";
    try {
      if (secondary && this.hass.localize) {
        secondaryLabel =
          this.hass.localize(`ui.card.weather.attributes.${secondary}`) ||
          secondary;
      }
    } catch (e) {}

    return html`
      <div class="content ${this.numberElements > 1 ? "spacer" : ""}">
        <div class="icon-image">
          <span
            style="background: none, url('${iconUrl}') no-repeat; background-size: contain;"
          ></span>
        </div>
        <div class="info">
          <div class="name-state">
            <div class="state">${conditionText}</div>
            <div class="name">${title}</div>
          </div>
          <div class="temp-attribute">
            <div class="temp">
              ${temp == null ? "" : unit == "°F" ? Math.round(temp) : temp}
              <span>${unit}</span>
            </div>
            ${secondaryVal != null
              ? html`
                  <div class="attribute">
                    ${secondaryLabel} ${secondaryVal}
                    ${this.getUnit(secondary)}
                  </div>
                `
              : ""}
          </div>
        </div>
      </div>
    `;
  }

  renderDetails(stateObj, lang) {
    const sun = this.hass.states["sun.sun"];
    let next_rising;
    let next_setting;

    if (sun) {
      next_rising = new Date(sun.attributes.next_rising).toLocaleTimeString(
        lang,
        { hour: "2-digit", minute: "2-digit" }
      );
      next_setting = new Date(sun.attributes.next_setting).toLocaleTimeString(
        lang,
        { hour: "2-digit", minute: "2-digit" }
      );
    }

    this.numberElements++;
    const a = stateObj.attributes;
    const windDir = this._windLabel(a.wind_bearing, lang);
    const summary =
      a.forecast_summary ||
      a.forecast_hourly ||
      a.forecast_minutely ||
      null;

    return html`
      <div class="${this.numberElements > 1 ? "spacer" : ""}">
        ${summary
          ? html`
              <ul class="summary">
                <li>
                  <span class="ha-icon"
                    ><ha-icon icon="mdi:clock-outline"></ha-icon
                  ></span>
                  ${summary}
                </li>
              </ul>
            `
          : ""}
        <ul class="variations">
          <li>
            <span class="ha-icon"
              ><ha-icon icon="mdi:water-percent"></ha-icon
            ></span>
            ${a.humidity != null ? a.humidity : ""}<span class="unit"> % </span>
            <br />
            <span class="ha-icon"
              ><ha-icon icon="mdi:weather-windy"></ha-icon
            ></span>
            ${windDir} ${a.wind_speed != null ? a.wind_speed : ""}
            <span class="unit">
              ${a.wind_speed_unit || `${this.getUnit("length")}/h`}
            </span>
            <br />
            ${next_rising
              ? html`
                  <span class="ha-icon"
                    ><ha-icon icon="mdi:weather-sunset-up"></ha-icon
                  ></span>
                  ${next_rising}
                `
              : ""}
          </li>
          <li>
            <span class="ha-icon"><ha-icon icon="mdi:gauge"></ha-icon></span>
            ${a.pressure != null ? a.pressure : ""}
            <span class="unit">
              ${a.pressure_unit || this.getUnit("air_pressure")}
            </span>
            <br />
            <span class="ha-icon"
              ><ha-icon icon="mdi:weather-fog"></ha-icon
            ></span>
            ${a.visibility != null ? a.visibility : ""}
            <span class="unit">
              ${a.visibility_unit || this.getUnit("length")}
            </span>
            <br />
            ${next_setting
              ? html`
                  <span class="ha-icon"
                    ><ha-icon icon="mdi:weather-sunset-down"></ha-icon
                  ></span>
                  ${next_setting}
                `
              : ""}
          </li>
        </ul>
      </div>
    `;
  }

  renderDailyForecast(forecast, lang) {
    if (!forecast || !forecast.forecast || forecast.forecast.length === 0) {
      return html``;
    }
    this.numberElements++;
    const limit = this._config.number_of_forecasts || 5;
    const days = forecast.forecast.slice(0, limit);
    return html`
      <div
        class="forecast clear ${this.numberElements > 1 ? "spacer" : ""}"
        @scroll="${this._dscroll}"
      >
        ${days.map(
          (daily) => html`
            <div class="day">
              <span class="dayname">${this._today(daily.datetime, lang)}</span>
              <br />
              <span class="dayname"
                >${new Date(daily.datetime).toLocaleDateString(lang, {
                  month: "2-digit",
                  day: "2-digit",
                })}</span
              >
              <br />
              <i
                class="icon"
                style="background: none, url('${this.getWeatherIcon(
                  (daily.condition || "cloudy").toLowerCase()
                )}') no-repeat; background-size: contain;"
              ></i>
              <br />
              <span class="highTemp"
                >${(() => {
                  const t =
                    daily.temperature ?? daily.native_temperature ?? null;
                  return t != null
                    ? html`${t}${this.getUnit("temperature")}`
                    : "";
                })()}</span
              >
              ${(() => {
                const low = daily.templow ?? daily.native_templow;
                return low !== undefined && low !== null
                  ? html`
                      <br /><span class="lowTemp"
                        >${low}${this.getUnit("temperature")}</span
                      >
                    `
                  : "";
              })()}
              ${!this._config.hide_precipitation &&
              (daily.precipitation ?? daily.native_precipitation) != null
                ? html`
                    <br /><span class="lowTemp"
                      >${Math.round(
                        (daily.precipitation ?? daily.native_precipitation) *
                          100
                      ) / 100}${this.getUnit("precipitation")}</span
                    >
                  `
                : ""}
            </div>
          `
        )}
      </div>
    `;
  }

  renderHourlyForecast(forecast, lang) {
    if (!forecast || !forecast.forecast || forecast.forecast.length === 0) {
      return html``;
    }
    const hourly = forecast.forecast;
    this.numberElements++;
    let showdata = this.showTarget || 0;
    if (showdata >= hourly.length) {
      showdata = Math.max(hourly.length - 1, 0);
    }
    const cur = hourly[showdata] || hourly[0];
    const condText = this._conditionLabel(cur.condition);
    const precip =
      cur.precipitation ?? cur.native_precipitation ?? 0;
    const pop = cur.precipitation_probability;

    return html`
      <div
        class="forecast clear hourly-forecast ${this.numberElements > 1
          ? "spacer"
          : ""}"
        @scroll="${this._hscroll}"
      >
        ${hourly.map(
          (item, i) => html`
            <div
              class="hourly${i > hourly.length - 5 ? " last5" : ""} d${new Date(
                item.datetime
              ).toLocaleTimeString("en-US", {
                hour: "numeric",
                hour12: false,
              })}"
            >
              <span
                class="dayname ${new Date(item.datetime).getHours() == 12
                  ? "show"
                  : ""}"
                >${new Date(item.datetime).toLocaleTimeString(lang, {
                  month: "2-digit",
                  day: "2-digit",
                  hour: "numeric",
                  hour12: false,
                })}</span
              >
              <i
                class="icon"
                style="background: none${i > 0 &&
                (item.condition || "") === (hourly[i - 1].condition || "")
                  ? ""
                  : ", url(" +
                    this.getWeatherIcon(
                      (item.condition || "cloudy").toLowerCase()
                    ) +
                    ") no-repeat"}; background-size: contain;"
              ></i>
              <br />
              <span class="dayname">.</span>
              <span
                style="border-top-color: rgb(${this.tempCOLOR[i] ||
                "128,128,128"});border-top-width:${this._tempBarWidth(
                  item.temperature ?? item.native_temperature
                )}px"
                class="dtemp"
                >.</span
              >
              <span
                style="border-top-color: hsla(220, 100%, ${((item.precipitation_probability != null
                  ? 100 - item.precipitation_probability
                  : 50) *
                  0.5) +
                50}%, 1);"
                class="cloudrate"
                >.</span
              >
              <span
                style="border-top-color: hsla(195, 100%, ${(4.8 -
                  Math.min(
                    Number(
                      item.precipitation ?? item.native_precipitation ?? 0
                    ),
                    4.8
                  )) *
                  (50 / 4.8) +
                50}%, 1);"
                class="precipitation"
                >.</span
              >
            </div>
          `
        )}
        <div class="show hourly showdata">
          <span class="dayname"
            >${new Date(cur.datetime).toLocaleTimeString(lang, {
              month: "2-digit",
              day: "2-digit",
              hour: "numeric",
              hour12: false,
            })}</span
          >
          <span class="icon"></span>
          <span class="dayname">${condText}</span>
          <span class="dtemp"
            >${cur.temperature ??
            cur.native_temperature ??
            ""}${this.getUnit("temperature")}</span
          >
          <span class="cloudrate"
            >${pop != null ? `${Math.round(pop)}%` : ""}</span
          >
          <span class="precipitation"
            >${Math.round(Number(precip) * 100) / 100}${this.getUnit(
              "precipitation"
            )}</span
          >
        </div>
      </div>
    `;
  }

  _computeHourlyColors(hourly) {
    if (!Array.isArray(hourly) || !hourly.length) {
      this.tempCOLOR = [];
      return;
    }
    let tempMAX = hourly[0].temperature ?? hourly[0].native_temperature ?? 0;
    let tempMIN = tempMAX;
    hourly.forEach((item) => {
      const t = item.temperature ?? item.native_temperature;
      if (t == null) return;
      if (t > tempMAX) tempMAX = t;
      if (t < tempMIN) tempMIN = t;
    });
    this.tempMAX = tempMAX;
    this.tempMIN = tempMIN;
    const span = tempMAX - tempMIN || 1;
    this.tempCOLOR = hourly.map((item) => {
      const t = item.temperature ?? item.native_temperature ?? tempMIN;
      return (
        Math.round(255 * ((t - tempMIN) / span)) +
        "," +
        Math.round(66 + 150 * (1 - (t - tempMIN) / span)) +
        "," +
        Math.round(255 * (1 - (t - tempMIN) / span))
      );
    });
  }

  _tempBarWidth(temp) {
    if (temp == null || this.tempMAX == null || this.tempMIN == null) {
      return 3;
    }
    const span = this.tempMAX - this.tempMIN || 1;
    return ((temp - this.tempMIN) / span) * 7 + 3;
  }

  _conditionLabel(condition) {
    const c = String(condition || "").toLowerCase();
    const map = {
      clear: "晴",
      "clear-night": "晴",
      cloudy: "阴",
      fog: "雾",
      hail: "冰雹",
      lightning: "雷暴",
      "lightning-rainy": "雷阵雨",
      partlycloudy: "多云",
      pouring: "暴雨",
      rainy: "雨",
      snowy: "雪",
      "snowy-rainy": "雨夹雪",
      sunny: "晴",
      windy: "大风",
      "windy-variant": "大风",
      dust: "浮尘",
      exceptional: "异常",
    };
    if (isZh(this.hass?.selectedLanguage || this.hass?.language)) {
      return map[c] || c;
    }
    return c;
  }

  _today(date, lang) {
    let retext = new Date(date).toLocaleDateString(lang, {
      weekday: "short",
    });
    const inDate = new Date(date);
    const nowDate = new Date();
    if (
      inDate.getFullYear() === nowDate.getFullYear() &&
      inDate.getMonth() === nowDate.getMonth() &&
      inDate.getDate() === nowDate.getDate()
    ) {
      try {
        retext =
          this.hass.localize(
            "ui.components.date-range-picker.ranges.today"
          ) || (isZh(lang) ? "今天" : "Today");
      } catch (e) {
        retext = isZh(lang) ? "今天" : "Today";
      }
    }
    return retext;
  }

  _dscroll(e) {
    const Dforecast = e.target;
    const Hforecast = e.target.nextElementSibling;
    if (!Hforecast || !Hforecast.classList.contains("hourly-forecast")) {
      return;
    }
    const dSpan = Dforecast.scrollWidth - Dforecast.offsetWidth;
    const hSpan = Hforecast.scrollWidth - Hforecast.offsetWidth;
    if (dSpan <= 0) return;
    Hforecast.scrollLeft = Dforecast.scrollLeft * (hSpan / dSpan);
  }

  _adjustScrollPosition() {
    if (
      !this._config ||
      this._config.forecast_hourly === false ||
      !this._forecastHourly?.forecast?.length
    ) {
      return;
    }
    const hourly = this._forecastHourly.forecast;
    const now = new Date();
    let currentHourIndex = 0;
    for (let i = 0; i < hourly.length; i++) {
      if (new Date(hourly[i].datetime) >= now) {
        currentHourIndex = i;
        break;
      }
    }
    const forecastContainer = this.shadowRoot?.querySelector(
      ".hourly-forecast"
    );
    if (!forecastContainer) return;
    const hourlyItems = forecastContainer.querySelectorAll(".hourly:not(.show)");
    if (!hourlyItems.length) return;
    const itemWidth = hourlyItems[0].offsetWidth;
    const scrollLeft =
      (itemWidth * (hourlyItems.length - 1) - forecastContainer.clientWidth) *
      (currentHourIndex / Math.max(hourlyItems.length - 1, 1));
    forecastContainer.scroll(Math.max(0, scrollLeft), 0);
    this._hscroll({ target: forecastContainer });
  }

  _hscroll(e) {
    const Hforecast = e?.target;
    if (!Hforecast) return;
    const children = Array.from(Hforecast.children).filter((el) =>
      el.classList.contains("hourly")
    );
    const showEl = Hforecast.querySelector(".showdata");
    const Hs = children.length - (showEl ? 1 : 0);
    if (Hs <= 0) return;
    const scrollWidth = Hs * 25;
    const maxScroll = scrollWidth - Hforecast.clientWidth;
    if (maxScroll <= 0) {
      if (showEl) showEl.style.left = "0px";
      return;
    }
    let i = Math.floor(Hforecast.scrollLeft / (maxScroll / Hs));
    let offset_data = (Hforecast.scrollLeft * scrollWidth) / maxScroll;
    offset_data =
      offset_data > scrollWidth - 25 ? scrollWidth - 25 : offset_data;
    i = i >= Hs ? Hs - 1 : i;
    if (i < 0) i = 0;

    if (i > Hs / 2) {
      offset_data = offset_data - 85;
      showEl?.classList.add("right");
    } else {
      showEl?.classList.remove("right");
    }
    if (showEl) {
      showEl.style.left = offset_data + "px";
    }
    if (i === this.showTarget) return;
    this.showTarget = i;
  }

  getWeatherIcon(condition, sun) {
    const c = (condition || "cloudy").toLowerCase();
    const night = sun && sun.state === "below_horizon";
    const baseRaw = this._config.icons || DEFAULT_ICONS;
    const base = baseRaw.endsWith("/") ? baseRaw : `${baseRaw}/`;
    const colorful =
      this._config.icon_style === "colorfulclouds" ||
      /colorfulclouds/i.test(base);

    let name;
    if (colorful) {
      const map = night ? colorfulIconsNight : colorfulIconsDay;
      name = map[c] || colorfulIconsDay.cloudy;
    } else {
      const map = night ? weatherIconsNight : weatherIconsDay;
      name = map[c] || weatherIconsDay.cloudy;
    }
    return `${base}${name}.svg`;
  }

  getUnit(measure) {
    const lengthUnit = this.hass.config.unit_system.length;
    switch (measure) {
      case "air_pressure":
      case "pressure":
        return lengthUnit === "km" ? "hPa" : "inHg";
      case "length":
      case "visibility":
        return lengthUnit;
      case "wind_speed":
        return `${lengthUnit}/h`;
      case "precipitation":
        return lengthUnit === "km" ? "mm" : "in";
      case "humidity":
      case "precipitation_probability":
        return "%";
      default:
        return this.hass.config.unit_system[measure] || "";
    }
  }

  _windLabel(bearing, lang) {
    if (bearing === undefined || bearing === null || bearing === "") {
      return "";
    }
    if (typeof bearing === "string" && Number.isNaN(Number(bearing))) {
      return bearing;
    }
    const n = Number(bearing);
    if (Number.isNaN(n)) {
      return "";
    }
    const dirs = isZh(lang) ? windDirectionsZh : windDirectionsEn;
    return dirs[parseInt((n + 11.25) / 22.5, 10)] || "";
  }

  _handleClick() {
    fireEvent(this, "hass-more-info", { entityId: this._config.entity });
  }

  getCardSize() {
    return 3;
  }

  static get styles() {
    return css`
      ha-card.weather-fx {
        cursor: pointer;
        margin: auto;
        overflow: hidden;
        padding: 1em;
        position: relative;
        background-color: var(
          --ha-card-background,
          var(--card-background-color, var(--primary-background-color, #fff))
        );
        background-color: color-mix(
          in srgb,
          var(--ha-card-background, var(--card-background-color, var(--primary-background-color, #fff))) 55%,
          transparent
        );
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        box-shadow: var(--ha-card-box-shadow, none);
        border-width: var(--ha-card-border-width, 1px);
        border-style: solid;
        border-color: var(--ha-card-border-color, var(--divider-color, #d9d9d9));
        border-color: color-mix(
          in srgb,
          var(--ha-card-border-color, var(--divider-color, #d9d9d9)) 50%,
          transparent
        );
      }

      .card-content {
        position: relative;
        z-index: 2;
      }

      .fx {
        position: absolute;
        inset: 0;
        z-index: 0;
        pointer-events: none;
        overflow: hidden;
        border-radius: var(--ha-card-border-radius, 12px);
      }

      .fx-tint {
        position: absolute;
        inset: 0;
        opacity: 0.45;
        background: transparent;
      }

      .weather-fx--sunny .fx-tint {
        background: radial-gradient(
          ellipse 90% 80% at 85% 0%,
          color-mix(in srgb, #ffca28 70%, transparent),
          color-mix(in srgb, #ffecb3 35%, transparent) 45%,
          transparent 72%
        );
      }
      .weather-fx--clear-night .fx-tint {
        background: radial-gradient(
          ellipse at 80% 8%,
          color-mix(in srgb, #7986cb 55%, transparent),
          color-mix(in srgb, #283593 35%, transparent) 55%,
          transparent 100%
        );
      }
      .weather-fx--partlycloudy .fx-tint {
        background:
          radial-gradient(
            ellipse 55% 50% at 88% 0%,
            color-mix(in srgb, #ffd54f 55%, transparent),
            transparent 58%
          ),
          linear-gradient(
            180deg,
            color-mix(in srgb, #64b5f6 40%, transparent),
            transparent 70%
          );
      }
      .weather-fx--partlycloudy-night .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #5c6bc0 45%, transparent),
          transparent 70%
        );
      }
      .weather-fx--cloudy .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #546e7a 28%, transparent),
          color-mix(in srgb, #78909c 16%, transparent) 45%,
          transparent 100%
        );
      }
      .weather-fx--fog .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #90a4ae 40%, transparent),
          color-mix(in srgb, #eceff1 35%, transparent) 60%,
          transparent 100%
        );
      }
      .weather-fx--dust .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #8d6e63 45%, transparent),
          color-mix(in srgb, #d7ccc8 30%, transparent) 55%,
          transparent 100%
        );
      }
      .weather-fx--rainy .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #455a64 40%, transparent),
          color-mix(in srgb, #1e88e5 35%, transparent) 100%
        );
      }
      .weather-fx--pouring .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #212121 45%, transparent),
          color-mix(in srgb, #0d47a1 40%, transparent) 100%
        );
      }
      .weather-fx--hail .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #37474f 40%, transparent),
          color-mix(in srgb, #607d8b 30%, transparent) 100%
        );
      }
      .weather-fx--lightning .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #000000 45%, transparent),
          color-mix(in srgb, #37474f 30%, transparent) 100%
        );
      }
      .weather-fx--thunder .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #0d1333 45%, transparent),
          color-mix(in srgb, #0d47a1 40%, transparent) 100%
        );
      }
      .weather-fx--snowy .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #90caf9 40%, transparent),
          color-mix(in srgb, #e3f2fd 30%, transparent) 55%,
          transparent 100%
        );
      }
      .weather-fx--sleet .fx-tint {
        background: linear-gradient(
          180deg,
          color-mix(in srgb, #546e7a 40%, transparent),
          color-mix(in srgb, #64b5f6 35%, transparent) 100%
        );
      }
      .weather-fx--windy .fx-tint {
        background: linear-gradient(
          90deg,
          color-mix(in srgb, #29b6f6 40%, transparent),
          color-mix(in srgb, #e1f5fe 25%, transparent) 50%,
          transparent 80%
        );
      }
      .weather-fx--windy-variant .fx-tint {
        background:
          radial-gradient(ellipse 50% 45% at 88% 0%, color-mix(in srgb, #ffca28 50%, transparent), transparent 58%),
          linear-gradient(90deg, color-mix(in srgb, #29b6f6 35%, transparent), transparent 60%);
      }
      .weather-fx--windy-variant-night .fx-tint {
        background:
          radial-gradient(ellipse 40% 40% at 88% 8%, color-mix(in srgb, #7986cb 50%, transparent), transparent 58%),
          linear-gradient(90deg, color-mix(in srgb, #29b6f6 28%, transparent), transparent 60%);
      }
      .weather-fx--exceptional .fx-tint {
        background: radial-gradient(
          ellipse at 50% 35%,
          color-mix(in srgb, #ff3d00 50%, transparent),
          transparent 70%
        );
      }

      .fx-sun {
        position: absolute;
        z-index: 2;
        top: 0.5em;
        right: 0.5em;
        width: 4em;
        height: 4em;
        border-radius: 50%;
        background: radial-gradient(circle at 35% 35%, #fffde7, #ffca28 45%, #ff6f00 100%);
        box-shadow:
          0 0 22px #ffc107,
          0 0 44px #ff9800,
          0 0 64px #ff6f00;
        animation: fx-pulse 2.4s ease-in-out infinite;
        opacity: 1;
      }
      .fx-sun--soft {
        width: 3em;
        height: 3em;
        opacity: 1;
        animation-name: fx-pulse-soft;
      }
      .fx-rays {
        position: absolute;
        z-index: 1;
        inset: 0;
        pointer-events: none;
        transform-origin: calc(100% - 2.5em) 2.5em;
        animation: fx-rays-spin 48s linear infinite;
      }
      .fx-rays--soft {
        transform-origin: calc(100% - 2em) 2em;
        animation-duration: 64s;
      }
      .fx-beam {
        position: absolute;
        top: 2.5em;
        left: calc(100% - 2.5em);
        width: var(--w, 2em);
        height: 220%;
        margin-left: calc(var(--w, 2em) / -2);
        transform-origin: 50% 0;
        transform: rotate(var(--a, 45deg));
        clip-path: polygon(48% 0, 52% 0, 78% 100%, 22% 100%);
        background-image:
          linear-gradient(
            180deg,
            color-mix(in srgb, #fffde7 70%, transparent),
            color-mix(in srgb, #ffecb3 40%, transparent) 38%,
            transparent 88%
          ),
          linear-gradient(
            180deg,
            transparent,
            #fff 12%,
            color-mix(in srgb, #fffde7 75%, transparent) 28%,
            transparent 55%
          );
        background-repeat: no-repeat;
        background-size: 100% 100%, 100% 50%;
        background-position: 0 0, 0 -40%;
        filter: blur(0.5px);
        mix-blend-mode: screen;
        animation: fx-beam-flow 1.6s linear infinite;
        animation-delay: var(--d, 0s);
        opacity: 0.95;
      }
      .weather-fx--sunny .fx-beam {
        height: 9em;
      }
      .fx-rays--soft .fx-beam {
        top: 2em;
        left: calc(100% - 2em);
        opacity: 0.5;
        animation-duration: 2.4s;
      }
      .fx-spark {
        position: absolute;
        top: var(--y, 20%);
        left: var(--x, 10%);
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #fffde7;
        box-shadow: 0 0 12px #ffc107, 0 0 20px #ff9800;
        opacity: 0;
        animation: fx-sparkle calc(1.6s + var(--i) * 0.2s) ease-in-out infinite;
        animation-delay: calc(var(--i) * -0.25s);
      }

      .fx-moon {
        position: absolute;
        z-index: 2;
        top: 0.5em;
        right: 0.5em;
        width: 3.6em;
        height: 3.6em;
        border-radius: 50%;
        background: radial-gradient(circle at 30% 30%, #fff, #cfd8dc);
        box-shadow: 0 0 30px #90caf9, 0 0 50px #e3f2fd;
        opacity: 1;
        animation: fx-pulse 3.5s ease-in-out infinite;
      }
      .fx-moon--soft {
        opacity: 1;
        width: 3em;
        height: 3em;
      }

      .fx-star {
        position: absolute;
        top: var(--y, 10%);
        left: var(--x, 10%);
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: #fff;
        box-shadow: 0 0 6px #fff, 0 0 10px #e3f2fd;
        opacity: 1;
        animation: fx-twinkle calc(1.2s + var(--i) * 0.15s) ease-in-out infinite;
        animation-delay: calc(var(--i) * -0.2s);
      }

      .fx-shade {
        position: absolute;
        top: -8%;
        left: -5%;
        right: -5%;
        height: 65%;
        background: linear-gradient(180deg, color-mix(in srgb, #455a64 28%, transparent), transparent);
        animation: fx-shade-pulse 3.5s ease-in-out infinite alternate;
        opacity: 0.55;
      }
      .fx-shade--2 {
        top: auto;
        bottom: -5%;
        height: 45%;
        background: linear-gradient(0deg, color-mix(in srgb, #607d8b 22%, transparent), transparent);
        animation-duration: 4.5s;
        animation-direction: alternate-reverse;
        opacity: 0.4;
      }
      .fx-shade--3 {
        top: 25%;
        height: 40%;
        background: linear-gradient(90deg, transparent, color-mix(in srgb, #90a4ae 20%, transparent), transparent);
        animation: fx-shade-sweep 5s ease-in-out infinite alternate;
        opacity: 0.35;
      }

      .fx-mist {
        position: absolute;
        left: -15%;
        right: -15%;
        bottom: 5%;
        height: 55%;
        background: linear-gradient(
          180deg,
          transparent,
          color-mix(in srgb, #f5f5f5 55%, transparent)
        );
        filter: blur(4px);
        animation: fx-mist-move 5s ease-in-out infinite alternate;
        opacity: 0.85;
      }
      .fx-mist--2 {
        bottom: -5%;
        height: 40%;
        animation-duration: 7s;
        animation-direction: alternate-reverse;
        opacity: 0.75;
      }
      .fx-mist--3 {
        top: 10%;
        bottom: auto;
        height: 45%;
        background: linear-gradient(180deg, color-mix(in srgb, #eceff1 45%, transparent), transparent);
        animation-duration: 6s;
        opacity: 0.7;
      }
      .fx-mist--cloudy {
        background: linear-gradient(
          180deg,
          transparent,
          color-mix(in srgb, #90a4ae 40%, transparent)
        );
        opacity: 0.7;
        animation-duration: 7s;
      }

      .fx-haze {
        position: absolute;
        top: var(--y, 20%);
        left: var(--x, 10%);
        width: var(--sz, 4px);
        height: var(--sz, 4px);
        border-radius: 50%;
        background: #78909c;
        opacity: 0.7;
        filter: blur(0.5px);
        animation: fx-haze-float var(--dur, 4s) ease-in-out infinite alternate;
        animation-delay: calc(var(--i) * -0.25s);
      }

      .fx-dust {
        position: absolute;
        bottom: -8%;
        left: var(--x, 10%);
        width: var(--sz, 4px);
        height: var(--sz, 4px);
        border-radius: 50%;
        background: #6d4c41;
        box-shadow: 0 0 4px #8d6e63;
        opacity: 1;
        animation: fx-dust-rise var(--dur, 4s) linear infinite;
        animation-delay: calc(var(--i) * -0.2s);
      }

      .fx-gust {
        position: absolute;
        top: calc(12% + var(--i) * 6%);
        left: -25%;
        width: 36%;
        height: 4px;
        border-radius: 3px;
        background: linear-gradient(
          90deg,
          transparent,
          #e1f5fe,
          #29b6f6,
          transparent
        );
        opacity: 1;
        animation: fx-gust-move calc(1.6s + var(--i) * 0.15s) linear infinite;
        animation-delay: calc(var(--i) * -0.25s);
      }
      .fx-gust--strong {
        width: 48%;
        height: 5px;
        background: linear-gradient(
          90deg,
          transparent,
          #fff,
          #4fc3f7,
          #0288d1,
          transparent
        );
        animation-duration: calc(0.85s + var(--i) * 0.08s);
        top: calc(6% + var(--i) * 4.8%);
      }

      .fx-drop {
        position: absolute;
        top: -20%;
        left: var(--x, 10%);
        width: 3px;
        height: var(--len, 18px);
        border-radius: 2px;
        background: linear-gradient(
          180deg,
          #e3f2fd,
          #42a5f5
        );
        opacity: 1;
        transform: rotate(14deg);
        animation: fx-fall var(--dur, 0.6s) linear infinite;
        animation-delay: calc(var(--i) * -0.06s);
      }
      .fx-drop--light {
        width: 2.5px;
        height: var(--len, 16px);
        background: linear-gradient(180deg, #e3f2fd, #1e88e5);
      }
      .fx-drop--heavy {
        height: calc(var(--len, 18px) + 10px);
        width: 4.5px;
        background: linear-gradient(
          180deg,
          #fff,
          #64b5f6
        );
      }

      .fx-hail {
        position: absolute;
        top: -12%;
        left: var(--x, 10%);
        width: var(--sz, 8px);
        height: var(--sz, 8px);
        border-radius: 2px;
        background: #fff;
        box-shadow: 0 0 2px #90a4ae, inset 0 0 2px #cfd8dc;
        opacity: 1;
        animation: fx-hail-fall var(--dur, 0.45s) linear infinite;
        animation-delay: calc(var(--i) * -0.08s);
      }

      .fx-flake {
        position: absolute;
        top: -10%;
        left: var(--x, 10%);
        width: var(--sz, 6px);
        height: var(--sz, 6px);
        border-radius: 50%;
        background: #fff;
        box-shadow: 0 0 4px #fff;
        opacity: 1;
        animation: fx-snow var(--dur, 2.5s) linear infinite;
        animation-delay: calc(var(--i) * -0.15s);
      }

      .fx-flash {
        position: absolute;
        inset: 0;
        background: #fff;
        opacity: 0;
        animation: fx-flash 3.2s ease-in-out infinite;
      }
      .fx-bolt {
        position: absolute;
        top: 4%;
        left: 38%;
        width: 18px;
        height: 48%;
        background: #fffde7;
        clip-path: polygon(40% 0, 100% 0, 55% 42%, 90% 42%, 0 100%, 35% 48%, 5% 48%);
        filter: drop-shadow(0 0 10px #fff59d) drop-shadow(0 0 18px #ffee58);
        opacity: 0;
        animation: fx-bolt 3.2s ease-in-out infinite;
      }
      .fx-bolt--2 {
        left: 58%;
        top: 12%;
        height: 36%;
        width: 14px;
        animation-delay: 1.5s;
      }
      .fx-bolt--3 {
        left: 22%;
        top: 16%;
        height: 30%;
        width: 12px;
        animation-delay: 2.4s;
      }

      .fx-warn {
        position: absolute;
        inset: 0;
        background: radial-gradient(ellipse at 50% 40%, color-mix(in srgb, #ff3d00 45%, transparent), transparent 70%);
        animation: fx-warn-pulse 1.4s ease-in-out infinite;
        opacity: 0.75;
      }

      @keyframes fx-pulse {
        0%,
        100% {
          transform: scale(1);
        }
        50% {
          transform: scale(1.12);
        }
      }
      @keyframes fx-pulse-soft {
        0%,
        100% {
          transform: scale(1);
        }
        50% {
          transform: scale(1.1);
        }
      }
      @keyframes fx-rays-spin {
        to {
          transform: rotate(360deg);
        }
      }
      @keyframes fx-beam-flow {
        from {
          background-position: 0 0, 0 -40%;
        }
        to {
          background-position: 0 0, 0 180%;
        }
      }
      @keyframes fx-sparkle {
        0%,
        100% {
          opacity: 0.5;
          transform: scale(0.6);
        }
        40% {
          opacity: 1;
          transform: scale(1.5);
        }
        70% {
          opacity: 0.85;
          transform: scale(1);
        }
      }
      @keyframes fx-twinkle {
        0%,
        100% {
          opacity: 0.45;
          transform: scale(0.7);
        }
        50% {
          opacity: 1;
          transform: scale(1.6);
        }
      }
      @keyframes fx-mist-move {
        from {
          transform: translateX(-12%);
        }
        to {
          transform: translateX(12%);
        }
      }
      @keyframes fx-shade-pulse {
        from {
          opacity: 0.35;
          transform: translateY(0);
        }
        to {
          opacity: 0.55;
          transform: translateY(4%);
        }
      }
      @keyframes fx-shade-sweep {
        from {
          transform: translateX(-8%);
          opacity: 0.25;
        }
        to {
          transform: translateX(8%);
          opacity: 0.45;
        }
      }
      @keyframes fx-haze-float {
        from {
          transform: translate3d(0, 0, 0) scale(1);
          opacity: 0.35;
        }
        to {
          transform: translate3d(6px, -18px, 0) scale(1.35);
          opacity: 0.85;
        }
      }
      @keyframes fx-dust-rise {
        from {
          transform: translate3d(0, 0, 0);
          opacity: 0.5;
        }
        30% {
          opacity: 1;
        }
        to {
          transform: translate3d(50px, -520px, 0);
          opacity: 0.4;
        }
      }
      @keyframes fx-gust-move {
        from {
          transform: translateX(0);
          opacity: 0.5;
        }
        15% {
          opacity: 1;
        }
        85% {
          opacity: 0.9;
        }
        to {
          transform: translateX(450%);
          opacity: 0.4;
        }
      }
      @keyframes fx-fall {
        from {
          transform: translate3d(0, 0, 0) rotate(14deg);
        }
        to {
          transform: translate3d(-22px, 520px, 0) rotate(14deg);
        }
      }
      @keyframes fx-hail-fall {
        from {
          transform: translate3d(0, 0, 0) rotate(0deg);
        }
        to {
          transform: translate3d(-14px, 520px, 0) rotate(220deg);
        }
      }
      @keyframes fx-snow {
        from {
          transform: translate3d(0, 0, 0);
        }
        to {
          transform: translate3d(var(--drift, 16px), 520px, 0);
        }
      }
      @keyframes fx-flash {
        0%,
        78%,
        100% {
          opacity: 0;
        }
        80% {
          opacity: 0.95;
        }
        83% {
          opacity: 0;
        }
        86% {
          opacity: 0.7;
        }
        89% {
          opacity: 0;
        }
      }
      @keyframes fx-bolt {
        0%,
        78%,
        100% {
          opacity: 0;
        }
        80% {
          opacity: 1;
        }
        83% {
          opacity: 0;
        }
        86% {
          opacity: 0.9;
        }
        89% {
          opacity: 0;
        }
      }
      @keyframes fx-warn-pulse {
        0%,
        100% {
          opacity: 0.55;
        }
        50% {
          opacity: 1;
        }
      }

      @media (prefers-reduced-motion: reduce) {
        .fx * {
          animation: none !important;
        }
      }

      .spacer {
        padding-top: 1em;
      }

      .clear {
        clear: both;
      }

      .content {
        display: flex;
        flex-wrap: nowrap;
        justify-content: space-between;
        align-items: center;
      }
      .icon-image {
        display: flex;
        align-items: center;
        min-width: 96px;
      }
      .icon-image > * {
        flex: 0 0 74px;
        height: 74px;
        display: block;
        background-size: contain;
        background-position: center center;
        background-repeat: no-repeat;
      }
      .info {
        display: flex;
        justify-content: space-between;
        flex-grow: 1;
        overflow: hidden;
      }
      .temp-attribute {
        text-align: right;
        margin-right: 5px;
      }
      .temp-attribute .temp {
        position: relative;
        margin-right: 24px;
        font-size: 28px;
        line-height: 1.2;
        color: var(--primary-text-color);
      }
      .temp-attribute .temp span {
        position: absolute;
        font-size: 24px;
        top: 1px;
      }
      .state {
        font-size: 28px;
        line-height: 1.2;
        color: var(--primary-text-color);
      }
      .name,
      .attribute {
        font-size: 14px;
        line-height: 1;
        color: var(--secondary-text-color);
      }
      .name-state {
        overflow: hidden;
        padding-right: 12px;
        width: 100%;
      }
      .name,
      .state {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .attribute {
        white-space: nowrap;
      }

      .ha-icon {
        height: 18px;
        margin-right: 5px;
        color: var(--paper-item-icon-color);
      }

      .summary {
        list-style: none;
        padding: 0 0 0 14px;
        margin: 0;
        color: var(--primary-text-color);
        font-weight: 300;
      }

      .variations {
        display: flex;
        flex-flow: row wrap;
        justify-content: space-between;
        font-weight: 300;
        color: var(--primary-text-color);
        list-style: none;
        margin-top: 1em;
        padding: 0;
      }

      .variations li {
        flex-basis: auto;
      }

      .variations li:first-child {
        padding-left: 1em;
      }

      .variations li:last-child {
        padding-right: 1em;
      }

      .unit {
        font-size: 0.8em;
      }

      .forecast {
        width: 100%;
        margin: 0 auto;
        display: flex;
        overflow-x: auto;
        position: relative;
      }

      ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
      }
      ::-webkit-scrollbar-track {
        border-radius: 3px;
        background: rgba(0, 0, 0, 0.06);
        -webkit-box-shadow: inset 0 0 5px rgba(0, 0, 0, 0.08);
      }
      ::-webkit-scrollbar-thumb {
        border-radius: 3px;
        background: rgba(0, 0, 0, 0.12);
        -webkit-box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.2);
      }

      .day {
        display: block;
        width: 20%;
        flex: none;
        text-align: center;
        color: var(--primary-text-color);
        border-right: 0.1em solid #d9d9d9;
        line-height: 2;
        box-sizing: border-box;
        padding-bottom: 1em;
      }

      .hourly {
        display: block;
        width: 25px;
        line-height: 2;
        flex: none;
        text-align: center;
        color: var(--primary-text-color);
        padding-bottom: 1em;
        overflow: visible;
        word-break: keep-all;
      }

      .dayname {
        text-transform: uppercase;
        white-space: nowrap;
        word-break: keep-all;
      }

      .forecast .day:first-child {
        margin-left: 0;
      }

      .forecast .day:nth-last-child(1) {
        border-right: none;
        margin-right: 0;
      }

      .highTemp {
        font-weight: bold;
      }

      .lowTemp {
        color: var(--secondary-text-color);
      }

      .icon {
        width: 42px;
        height: 42px;
        display: inline-block;
        vertical-align: middle;
        background-size: contain;
        background-position: center center;
        background-repeat: no-repeat;
        text-indent: -9999px;
      }

      .hourly .icon {
        width: 25px;
        height: 25px;
      }

      .hourly .dayname,
      .hourly .cloudrate,
      .hourly .precipitation {
        color: #00000000;
      }

      .hourly.show {
        border-left: 0.1em solid #d9d9d9;
        box-sizing: border-box;
      }

      .hourly.show .dayname,
      .hourly.show .dtemp,
      .hourly.show .precipitation,
      .hourly.show .cloudrate {
        color: var(--primary-text-color);
      }

      .dayname.show {
        color: var(--primary-text-color);
        margin: 0 6px;
      }

      .hourly.last5 {
        overflow: hidden;
      }

      .hourly.last5 > .dayname {
        color: #00000000;
      }

      .dtemp {
        font-weight: bold;
        display: block;
        border-top: solid 3px #fff;
        box-sizing: border-box;
        overflow: visible;
        color: #00000000;
        height: 35px;
        line-height: 35px;
      }

      .precipitation,
      .cloudrate {
        color: var(--secondary-text-color);
        display: block;
        border-top: solid 6px;
        overflow: visible;
        color: #00000000;
      }

      .showdata {
        position: absolute;
        width: 85px;
        left: 0;
      }

      .showdata > * {
        border-top-color: #00000000;
        position: relative;
        display: block;
        text-align: left;
        margin: 0 5px;
      }

      .showdata > .dayname {
        background: var(
          --ha-card-background,
          var(--card-background-color, white)
        );
      }

      .showdata.right {
        border-left: none;
        border-right: 0.1em solid #d9d9d9;
      }

      .showdata.right > * {
        text-align: right;
      }
    `;
  }
  }

  if (!customElements.get(CARD_TYPE)) {
    customElements.define(CARD_TYPE, WeatherForecastCard);
  }
  console.info(
    `%c ${CARD_TYPE} %c loaded `,
    "color:#fff;background:#03a9f4;padding:2px 4px;",
    "color:#03a9f4;background:transparent;padding:2px 4px;"
  );
}

(function bootWeatherForecastCard() {
  const base = resolveLitElement();
  if (base) {
    defineWeatherForecastCard(base);
    return;
  }
  let tries = 0;
  const timer = setInterval(() => {
    tries += 1;
    const lit = resolveLitElement();
    if (lit) {
      clearInterval(timer);
      defineWeatherForecastCard(lit);
      return;
    }
    if (tries > 100) {
      clearInterval(timer);
      console.error(
        `${CARD_TYPE}: LitElement base not found, check resource is JavaScript module`
      );
    }
  }, 100);
})();

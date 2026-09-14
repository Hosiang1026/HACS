const fireEvent = (node, type, detail, options) => {
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
};

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
    if (el) return Object.getPrototypeOf(el);
  }
  return window.LitElement || null;
}

function defineEditor(LitElement) {
  const html = LitElement.prototype.html;
  const css = LitElement.prototype.css;

  const LABELS = {
    zh: {
      entity: "天气实体",
      name: "名称",
      icons: "图标路径",
      current: "显示当前天气",
      details: "显示详细信息",
      forecast: "显示预报",
      forecast_daily: "每日预报",
      forecast_hourly: "小时预报",
      number_of_forecasts: "预报条数",
      hide_precipitation: "隐藏降水量",
      effects: "天气动态背景",
    },
    en: {
      entity: "Entity",
      name: "Name",
      icons: "Icons path",
      current: "Show current",
      details: "Show details",
      forecast: "Show forecast",
      forecast_daily: "Daily forecast",
      forecast_hourly: "Hourly forecast",
      number_of_forecasts: "Number of forecasts",
      hide_precipitation: "Hide precipitation",
      effects: "Weather effects",
    },
  };

  class WeatherForecastCardEditor extends LitElement {
    setConfig(config) {
      this._config = {
        current: true,
        details: true,
        forecast: true,
        forecast_daily: true,
        forecast_hourly: true,
        number_of_forecasts: 5,
        hide_precipitation: false,
        effects: true,
        ...config,
      };
    }

    static get properties() {
      return { hass: {}, _config: {} };
    }

    _t(key) {
      const lang = (this.hass?.selectedLanguage || this.hass?.language || "zh")
        .toLowerCase()
        .startsWith("zh")
        ? "zh"
        : "en";
      return LABELS[lang][key] || key;
    }

    render() {
      if (!this.hass || !this._config) {
        return html``;
      }

      if (customElements.get("ha-form")) {
        return html`
          <ha-form
            .hass=${this.hass}
            .data=${this._config}
            .schema=${this._schema()}
            .computeLabel=${this._computeLabel}
            @value-changed=${this._valueChanged}
          ></ha-form>
        `;
      }

      return this._legacyRender();
    }

    _schema() {
      return [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "weather" } },
        },
        { name: "name", selector: { text: {} } },
        { name: "icons", selector: { text: {} } },
        { name: "current", selector: { boolean: {} } },
        { name: "details", selector: { boolean: {} } },
        { name: "forecast", selector: { boolean: {} } },
        { name: "forecast_daily", selector: { boolean: {} } },
        { name: "forecast_hourly", selector: { boolean: {} } },
        {
          name: "number_of_forecasts",
          selector: { number: { min: 1, max: 15, mode: "box" } },
        },
        { name: "hide_precipitation", selector: { boolean: {} } },
        { name: "effects", selector: { boolean: {} } },
      ];
    }

    _computeLabel = (schema) => this._t(schema.name);

    _valueChanged(ev) {
      const value = ev.detail?.value || {};
      const next = { ...this._config, ...value };
      delete next.forecast_type;
      delete next.hourly_forecast;
      this._config = next;
      fireEvent(this, "config-changed", { config: this._config });
    }

    _legacyRender() {
      const entities = Object.keys(this.hass.states).filter(
        (eid) => eid.split(".")[0] === "weather"
      );
      const switches = [
        "current",
        "details",
        "forecast",
        "forecast_daily",
        "forecast_hourly",
        "hide_precipitation",
        "effects",
      ];
      return html`
        <div class="card-config">
          <ha-textfield
            .label=${this._t("name")}
            .value=${this._config.name || ""}
            .configValue=${"name"}
            @input=${this._legacyChanged}
          ></ha-textfield>
          <ha-textfield
            .label=${this._t("icons")}
            .value=${this._config.icons || ""}
            .configValue=${"icons"}
            @input=${this._legacyChanged}
          ></ha-textfield>
          <ha-select
            .label=${this._t("entity")}
            .value=${this._config.entity || ""}
            .configValue=${"entity"}
            @selected=${this._legacyChanged}
            @closed=${(ev) => ev.stopPropagation()}
          >
            ${entities.map(
              (entity) =>
                html`<mwc-list-item .value=${entity}>${entity}</mwc-list-item>`
            )}
          </ha-select>
          <div class="switches">
            ${switches.map(
              (key) => html`
                <label class="switch">
                  <ha-switch
                    .checked=${key === "hide_precipitation"
                      ? this._config[key] === true
                      : this._config[key] !== false}
                    .configValue=${key}
                    @change=${this._legacyChanged}
                  ></ha-switch>
                  <span>${this._t(key)}</span>
                </label>
              `
            )}
          </div>
          <ha-textfield
            .label=${this._t("number_of_forecasts")}
            type="number"
            min="1"
            max="15"
            .value=${this._config.number_of_forecasts || 5}
            .configValue=${"number_of_forecasts"}
            @input=${this._legacyChanged}
          ></ha-textfield>
        </div>
      `;
    }

    _legacyChanged(ev) {
      if (!this._config || !this.hass) {
        return;
      }
      const target = ev.target;
      const key = target.configValue;
      if (!key) {
        return;
      }
      let value =
        target.checked !== undefined
          ? target.checked
          : target.value !== undefined
            ? target.value
            : ev.detail?.value;
      if (key === "number_of_forecasts") {
        value = Number(value) || 5;
      }
      if (value === "") {
        const next = { ...this._config };
        delete next[key];
        this._config = next;
      } else {
        this._config = { ...this._config, [key]: value };
      }
      fireEvent(this, "config-changed", { config: this._config });
    }

    static get styles() {
      return css`
        .card-config {
          display: grid;
          gap: 12px;
        }
        .switches {
          display: grid;
          gap: 8px;
        }
        .switch {
          display: flex;
          align-items: center;
          gap: 8px;
        }
      `;
    }
  }

  if (!customElements.get("weather-forecast-card-editor")) {
    customElements.define(
      "weather-forecast-card-editor",
      WeatherForecastCardEditor
    );
  }
}

const _lit = resolveLitElement();
if (_lit) {
  defineEditor(_lit);
} else {
  let tries = 0;
  const timer = setInterval(() => {
    tries += 1;
    const lit = resolveLitElement();
    if (lit) {
      clearInterval(timer);
      defineEditor(lit);
    } else if (tries > 100) {
      clearInterval(timer);
    }
  }, 100);
}

/* TP-Link ER6020 AutoPortOnOff Lovelace card — served by the tplink_er6020 integration. */
const DOMAIN = "tplink_er6020";
const CARD = "tplink-er6020-card";

const I18N = {
  en: {
    title: "Router ports",
    home: "Home",
    away: "Away",
    unknown: "Unknown",
    polling: "Router polling",
    open: "Open",
    closed: "Closed",
    since: "since",
    never: "no changes yet",
    details: "Ports",
    no_events: "No events yet",
    hint: "Tap for details",
    controlled: "automated",
    active_hours: "Active hours",
    src: {
      away: "you left home",
      home: "you came home",
      schedule: "outside active hours",
      manual: "manually",
      router: "changed on the router",
    },
    auto: {
      away: "Away — ports open",
      home: "Home — ports closed",
      leaving: "Waiting for away delay",
      schedule: "Night — ports closed",
      paused: "Polling off — automation paused",
      error: "Failed to change ports — see notification / logs",
    },
    editor: {
      title: "Title",
      presence: "Presence entity",
      show_polling: "Show polling toggle",
      ports: "Ports to show (order with arrows)",
      none: "No ports found — is the integration set up?",
    },
  },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function lang(hass) {
  const l = (hass?.locale?.language || hass?.language || "en").slice(0, 2);
  return I18N[l] ? l : "en";
}

function fmt(hass, iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return d.toLocaleString(hass?.locale?.language || undefined, {
    ...(sameDay ? {} : { day: "2-digit", month: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Entities that belong to this integration. */
function discover(hass) {
  const ids = Object.values(hass?.entities || {})
    .filter((e) => e.platform === DOMAIN)
    .map((e) => e.entity_id);
  const st = (id) => hass.states[id];
  return {
    ports: ids.filter((id) => id.startsWith("switch.") && st(id)?.attributes?.rule !== undefined),
    polling: ids.find((id) => id.startsWith("switch.") && st(id) && "automation" in st(id).attributes),
    trackers: ids.filter((id) => id.startsWith("device_tracker.")),
  };
}

const STYLE = `
  ha-card { cursor: pointer; overflow: hidden; }
  .header { display: flex; align-items: center; gap: 8px; padding: 16px 16px 8px; }
  .header .title { flex: 1; font-size: 1.2em; font-weight: 500; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px;
          font-size: .85em; background: var(--secondary-background-color); color: var(--primary-text-color); }
  .chip.home { background: rgba(76,175,80,.15); color: var(--success-color, #4caf50); }
  .chip.away { background: rgba(255,152,0,.15); color: var(--warning-color, #ff9800); }
  .chip ha-icon { --mdc-icon-size: 16px; }
  .auto { padding: 0 16px 8px; color: var(--secondary-text-color); font-size: .85em; }
  .row { display: flex; align-items: center; gap: 12px; padding: 8px 16px; }
  .row ha-icon { color: var(--state-icon-color); }
  .row ha-icon.on { color: var(--warning-color, #ff9800); }
  .info { flex: 1; min-width: 0; }
  .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { color: var(--secondary-text-color); font-size: .85em; }
  .badge { font-size: .7em; padding: 0 6px; border-radius: 8px; margin-left: 6px; vertical-align: middle;
           background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .footer { padding: 4px 16px 12px; color: var(--secondary-text-color); font-size: .75em; text-align: right; }
  .sw { position: relative; width: 40px; height: 22px; border-radius: 11px; border: none; padding: 0; flex: none;
        background: var(--disabled-color, #bdbdbd); cursor: pointer; transition: background .2s; }
  .sw::after { content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%;
               background: #fff; transition: left .2s; }
  .sw.on { background: var(--primary-color); }
  .sw.on::after { left: 21px; }
  .sw:disabled { opacity: .4; cursor: default; }
  .sw.busy { opacity: .6; }
  .backdrop { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,.45); display: flex;
              align-items: center; justify-content: center; cursor: default; }
  .dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 16px;
            width: min(560px, calc(100vw - 32px)); max-height: calc(100vh - 64px); overflow: auto;
            box-shadow: 0 8px 32px rgba(0,0,0,.3); }
  .dialog .header { position: sticky; top: 0; background: inherit; z-index: 1;
                    border-bottom: 1px solid var(--divider-color); padding-bottom: 12px; }
  .close { background: none; border: none; color: inherit; cursor: pointer; padding: 4px; }
  .port { border-bottom: 1px solid var(--divider-color); padding-bottom: 8px; }
  .port:last-child { border-bottom: none; }
  .log { list-style: none; margin: 0; padding: 0 16px 0 52px; font-size: .85em; }
  .log li { display: flex; gap: 8px; padding: 2px 0; color: var(--secondary-text-color); }
  .log .t { min-width: 92px; }
  .log .s.on { color: var(--warning-color, #ff9800); }
  .log .s.off { color: var(--success-color, #4caf50); }
  .empty { padding: 0 16px 0 52px; font-size: .85em; color: var(--secondary-text-color); }
`;

class TplinkEr6020Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._open = false;
    this._busy = new Set();
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this._onKey = (ev) => {
      if (ev.key === "Escape" && this._open) this._setOpen(false);
    };
  }

  static getConfigElement() {
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    const { ports, trackers } = discover(hass);
    const controlled = ports.filter((id) => hass.states[id]?.attributes?.controlled);
    return { entities: controlled.length ? controlled : ports, presence_entity: trackers[0] };
  }

  setConfig(config) {
    this._config = { show_polling: true, ...config };
    this._sig = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    window.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
  }

  getCardSize() {
    return 2 + (this._config?.entities?.length || 2);
  }

  _entities() {
    const found = discover(this._hass);
    const ports = (this._config.entities?.length ? this._config.entities : found.ports).filter(
      (id) => this._hass.states[id]
    );
    // Details show every port: configured ones first, then the rest.
    const all = [...ports, ...found.ports.filter((id) => !ports.includes(id))];
    return {
      ports,
      all,
      polling: this._config.polling_entity || found.polling,
      presence: this._config.presence_entity || found.trackers[0],
    };
  }

  _render() {
    if (!this._hass || !this._config) return;
    const e = this._entities();
    const ids = [...e.all, e.polling, e.presence].filter(Boolean);
    const sig = JSON.stringify([
      this._open,
      [...this._busy],
      ids.map((id) => this._hass.states[id]?.last_updated),
      this._config,
    ]);
    if (sig === this._sig) return;
    this._sig = sig;

    const t = I18N[lang(this._hass)];
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        ${this._header(t, e, false)}
        ${this._automation(t, e)}
        ${e.ports.map((id) => this._row(t, id)).join("")}
        ${e.ports.length ? `<div class="footer">${t.hint}</div>` : ""}
      </ha-card>
      ${this._open ? this._dialog(t, e) : ""}
    `;
  }

  _header(t, e, inDialog) {
    const p = e.presence && this._hass.states[e.presence];
    let chip = "";
    if (p) {
      const cls = p.state === "home" ? "home" : p.state === "not_home" ? "away" : "";
      const label = cls === "home" ? t.home : cls === "away" ? t.away : t.unknown;
      const icon = cls === "home" ? "mdi:home" : cls === "away" ? "mdi:home-export-outline" : "mdi:help";
      chip = `<span class="chip ${cls}"><ha-icon icon="${icon}"></ha-icon>${label}
        ${cls ? `<span>· ${fmt(this._hass, p.last_changed)}</span>` : ""}</span>`;
    }
    const close = inDialog
      ? `<button class="close" data-close><ha-icon icon="mdi:close"></ha-icon></button>`
      : "";
    const title = inDialog ? t.details : this._config.title ?? t.title;
    return `<div class="header"><div class="title">${esc(title)}</div>${chip}${close}</div>`;
  }

  _automation(t, e) {
    const pol = e.polling && this._hass.states[e.polling];
    if (!pol) return "";
    const a = pol.attributes;
    const state = pol.state === "off" ? "paused" : a.automation;
    const text = [
      t.auto[state],
      a.active_from && a.active_to && a.active_from !== a.active_to
        ? `${t.active_hours}: ${a.active_from.slice(0, 5)}–${a.active_to.slice(0, 5)}`
        : "",
    ]
      .filter(Boolean)
      .join(" · ");
    const toggle = this._config.show_polling
      ? `<div class="row"><ha-icon icon="${pol.state === "on" ? "mdi:sync" : "mdi:sync-off"}"></ha-icon>
           <div class="info"><div class="name">${t.polling}</div></div>${this._switch(e.polling, pol.state === "on")}</div>`
      : "";
    return `${toggle}${text ? `<div class="auto">${esc(text)}</div>` : ""}`;
  }

  _switch(id, on, disabled = false) {
    const busy = this._busy.has(id);
    return `<button class="sw ${on ? "on" : ""} ${busy ? "busy" : ""}" role="switch" aria-checked="${on}"
      data-toggle="${esc(id)}" ${disabled || busy ? "disabled" : ""}></button>`;
  }

  _row(t, id) {
    const s = this._hass.states[id];
    if (!s) return "";
    const a = s.attributes;
    const on = s.state === "on";
    const last = (on ? a.last_on : a.last_off) || null;
    const status = `${on ? t.open : t.closed} ${last ? `${t.since} ${fmt(this._hass, last)}` : `· ${t.never}`}`;
    return `
      <div class="row">
        <ha-icon class="${on ? "on" : ""}" icon="${on ? "mdi:lan-connect" : "mdi:lan-disconnect"}"></ha-icon>
        <div class="info">
          <div class="name">${esc(a.rule)}${a.controlled ? `<span class="badge">${t.controlled}</span>` : ""}</div>
          <div class="sub">${esc(a.external_port)} → ${esc(a.ipaddr)}:${esc(a.internal_port)} ${esc(a.protocol || "")}</div>
          <div class="sub">${esc(status)}</div>
        </div>
        ${this._switch(id, on, s.state === "unavailable")}
      </div>`;
  }

  _dialog(t, e) {
    const ports = e.all
      .map((id) => {
        const log = [...(this._hass.states[id]?.attributes?.log || [])].reverse();
        const items = log.length
          ? `<ul class="log">${log
              .map(
                (ev) => `<li><span class="t">${fmt(this._hass, ev.ts)}</span>
                  <span class="s ${ev.state}">${ev.state === "on" ? t.open : t.closed}</span>
                  <span>${esc(t.src[ev.source] || ev.source)}</span></li>`
              )
              .join("")}</ul>`
          : `<div class="empty">${t.no_events}</div>`;
        return `<div class="port">${this._row(t, id)}${items}</div>`;
      })
      .join("");
    return `<div class="backdrop" data-backdrop><div class="dialog">${this._header(t, e, true)}${ports}</div></div>`;
  }

  _setOpen(open) {
    this._open = open;
    this._render();
  }

  async _onClick(ev) {
    const path = ev.composedPath();
    const toggle = path.find((el) => el.dataset?.toggle);
    if (toggle) {
      ev.stopPropagation();
      const id = toggle.dataset.toggle;
      const on = this._hass.states[id]?.state === "on";
      this._busy.add(id);
      this._render();
      try {
        await this._hass.callService("switch", on ? "turn_off" : "turn_on", { entity_id: id });
      } catch (err) {
        this.dispatchEvent(
          new CustomEvent("hass-notification", { detail: { message: err.message }, bubbles: true, composed: true })
        );
      } finally {
        this._busy.delete(id);
        this._render();
      }
      return;
    }
    if (path.find((el) => el.dataset && "close" in el.dataset)) return this._setOpen(false);
    if (path[0]?.dataset && "backdrop" in path[0].dataset) return this._setOpen(false);
    if (!this._open && path.find((el) => el.tagName === "HA-CARD")) this._setOpen(true);
  }
}

class TplinkEr6020CardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._render();
  }

  _ports() {
    const { ports } = discover(this._hass);
    const selected = (this._config.entities || []).filter((id) => ports.includes(id));
    return { selected, all: [...selected, ...ports.filter((id) => !selected.includes(id))] };
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = I18N[lang(this._hass)];
    const { selected, all } = this._ports();
    const { trackers } = discover(this._hass);
    const trackerOptions = [...new Set([...trackers, ...Object.keys(this._hass.states).filter((id) => id.startsWith("device_tracker.") || id.startsWith("person."))])];
    const name = (id) => this._hass.states[id]?.attributes?.rule || this._hass.states[id]?.attributes?.friendly_name || id;

    this.shadowRoot.innerHTML = `
      <style>
        label { display: block; margin: 12px 0 4px; color: var(--secondary-text-color); font-size: .9em; }
        input[type=text], select { width: 100%; box-sizing: border-box; padding: 8px; border-radius: 6px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        .check { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
        .port { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--divider-color); }
        .port span { flex: 1; }
        .port.off span { color: var(--secondary-text-color); }
        button { background: none; border: 1px solid var(--divider-color); border-radius: 6px; color: inherit;
          cursor: pointer; width: 32px; height: 28px; }
        button:disabled { opacity: .3; cursor: default; }
      </style>
      <label>${t.editor.title}</label>
      <input type="text" data-field="title" value="${esc(this._config.title ?? "")}" placeholder="${esc(t.title)}">
      <label>${t.editor.presence}</label>
      <select data-field="presence_entity">
        ${trackerOptions
          .map((id) => `<option value="${esc(id)}" ${id === this._config.presence_entity ? "selected" : ""}>${esc(this._hass.states[id]?.attributes?.friendly_name || id)} (${esc(id)})</option>`)
          .join("")}
      </select>
      <div class="check"><input type="checkbox" id="sp" data-field="show_polling" ${this._config.show_polling !== false ? "checked" : ""}>
        <span>${t.editor.show_polling}</span></div>
      <label>${t.editor.ports}</label>
      ${all.length ? "" : `<div>${t.editor.none}</div>`}
      ${all
        .map((id) => {
          const i = selected.indexOf(id);
          const on = i >= 0;
          return `<div class="port ${on ? "" : "off"}">
            <input type="checkbox" data-port="${esc(id)}" ${on ? "checked" : ""}>
            <span>${esc(name(id))}</span>
            <button data-move="-1" data-id="${esc(id)}" ${!on || i === 0 ? "disabled" : ""}>↑</button>
            <button data-move="1" data-id="${esc(id)}" ${!on || i === selected.length - 1 ? "disabled" : ""}>↓</button>
          </div>`;
        })
        .join("")}
    `;
  }

  _emit() {
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
  }

  _onChange(ev) {
    const el = ev.target;
    if (el.dataset.port) {
      const { selected } = this._ports();
      this._config.entities = el.checked ? [...selected, el.dataset.port] : selected.filter((id) => id !== el.dataset.port);
    } else if (el.dataset.field === "show_polling") {
      this._config.show_polling = el.checked;
    } else if (el.dataset.field) {
      if (el.value) this._config[el.dataset.field] = el.value;
      else delete this._config[el.dataset.field];
    } else return;
    this._emit();
  }

  _onClick(ev) {
    const btn = ev.composedPath().find((el) => el.dataset?.move);
    if (!btn) return;
    const { selected } = this._ports();
    const i = selected.indexOf(btn.dataset.id);
    const j = i + Number(btn.dataset.move);
    if (i < 0 || j < 0 || j >= selected.length) return;
    [selected[i], selected[j]] = [selected[j], selected[i]];
    this._config.entities = selected;
    this._emit();
  }
}

customElements.get(CARD) || customElements.define(CARD, TplinkEr6020Card);
customElements.get(`${CARD}-editor`) || customElements.define(`${CARD}-editor`, TplinkEr6020CardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "TP-Link ER6020 AutoPortOnOff",
    description: "Presence, port forwarding status, manual control and change log.",
    preview: true,
  });
}

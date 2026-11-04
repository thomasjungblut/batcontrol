// batcontrol dashboard - plain JavaScript, no build step, no network access
// beyond the batcontrol API itself.
'use strict'

// Relative to the page, so it also works behind a reverse-proxy subpath.
const API = new URL('api/v1/', document.baseURI).href
const TOKEN_KEY = 'batcontrol.token'
const FALLBACK_POLL_MS = 60000
const MIN_POLL_MS = 5000

const $ = (id) => document.getElementById(id)
let last = null
let pollTimer = null
let nextPollAt = 0

// ---- formatting -------------------------------------------------------------

const kwh = (wh, d = 1) => (wh == null ? '-' : `${(wh / 1000).toFixed(d)} kWh`)
const eur = (v, d = 2) => (v == null ? '-' : `${v.toFixed(d)} €`)
const ct = (v, d = 1) => (v == null ? '-' : `${(v * 100).toFixed(d)} ct`)
const clock = (ts) =>
  ts ? new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '-'
const span = (a, b) => `${clock(a)}–${clock(b)}`

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v
    else if (k === 'style') Object.assign(node.style, v)
    else node.setAttribute(k, v)
  }
  for (const c of children) if (c != null) node.append(c)
  return node
}

// ---- API --------------------------------------------------------------------

class Unauthorized extends Error {}

function token() {
  try { return sessionStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
}

function setToken(value) {
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch { /* lives for this page view only */ }
}

async function call(path, method = 'GET', body) {
  const headers = {}
  if (token()) headers.Authorization = `Bearer ${token()}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(API + path, {
    method,
    cache: 'no-store',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) throw new Unauthorized()
  const json = await res.json().catch(() => ({}))
  if (!res.ok || !json.ok) throw new Error(json.detail || `HTTP ${res.status}`)
  return json.data
}

// ---- rendering --------------------------------------------------------------

function renderBattery(s) {
  const b = s.battery
  const plan = s.plan
  $('soc').textContent = `${Math.round(b.soc)} %`
  $('socfill').style.width = `${Math.max(0, Math.min(100, b.soc))}%`
  $('socbar').setAttribute('aria-label', `State of charge ${Math.round(b.soc)} %`)
  const mark = $('reserve-mark')
  if (plan.reserve_wh > 0 && b.capacity_wh > 0) {
    mark.hidden = false
    mark.style.left = `${Math.min(100, b.min_soc + (plan.reserve_wh / b.capacity_wh) * 100)}%`
  } else {
    mark.hidden = true
  }
  $('usable').textContent = `${kwh(b.usable_wh)} usable of ${kwh(b.capacity_wh)}`
  const reserve = $('reserve')
  reserve.hidden = !(plan.reserve_wh > 0)
  reserve.className = plan.deficit_wh > 0 ? 'line amber' : 'line'
  reserve.textContent = `reserve ${kwh(plan.reserve_wh)}${plan.preview ? ' at 16:00' : ''}` +
    (plan.deficit_wh > 0 ? ` · short ${kwh(plan.deficit_wh)}` : '')
}

function renderSavings(s) {
  $('saving').textContent = eur(s.plan.saving_eur)
  $('saving-label').textContent =
    `planned, next 24 h${s.plan.preview ? ' · night is a preview' : ''}`
  $('monthly').textContent = `≈ ${eur(s.plan.monthly_saving_eur)} / month (× 30)`
}

function renderNow(s) {
  const charging = s.mode === 'charge'
  const mode = $('mode')
  mode.textContent = charging ? `CHARGING ${(s.charge_rate_w / 1000).toFixed(1)} kW` : 'NORMAL'
  mode.className = charging ? 'big mode amber' : 'big mode'
  $('headline').textContent = s.headline
  const button = $('manual')
  const manual = s.reason === 'manual' && s.manual_until
  button.dataset.action = manual ? 'cancel' : 'start'
  button.textContent = manual
    ? `>STOP MANUAL CHARGE (${clock(s.manual_until)})<`
    : '>CHARGE FULL SPEED FOR 1 H<'
}

function renderPlan(s) {
  const plan = s.plan
  $('plan-title').textContent =
    `PLAN ${span(plan.night_start, plan.night_end)}${plan.preview ? ' · PREVIEW' : ''}`
  const list = $('charges')
  list.replaceChildren(...plan.charges.map((c) => {
    const detail = c.reason === 'night_reserve'
      ? ` · ${span(c.compare_start, c.compare_end)} costs ${ct(c.compare_price)} (+${ct(c.spread)})`
      : ` · negative price (typical ${ct(c.compare_price)})`
    const classes = [c.active ? 'active' : '', c.reason === 'negative_price' ? 'negative' : '']
    return el('li', { class: classes.join(' ').trim(), title: c.explanation },
      el('span', { class: 'when' }, span(c.start, c.end)),
      el('span', { class: 'what' }, `charge ${kwh(c.energy_wh)} at ${ct(c.price)}`,
        el('span', { class: 'dim' }, detail)),
      el('span', { class: 'saving' }, eur(c.saving_eur)))
  }))
  const empty = $('empty')
  empty.hidden = plan.charges.length > 0
  empty.textContent = 'No grid charging planned. The battery covers the night, or no slot is ' +
    `${ct(s.min_price_difference, 0)} cheaper than the morning.`
  $('notes').replaceChildren(...plan.notes.map((n) => el('p', { class: 'dim small' }, `· ${n}`)))
}

function renderPrices(s) {
  const prices = s.prices
  const strip = $('strip')
  if (!prices.length) {
    strip.replaceChildren()
    $('legend').textContent = 'No prices.'
    return
  }
  const values = prices.map((p) => p.price)
  const lo = Math.min(...values)
  const hi = Math.max(...values, lo + 0.01)
  // Scaled to the actual range so a 10 ct spread is visible.
  const floor = lo < 0 ? lo : lo - (hi - lo) * 0.4
  strip.replaceChildren(...prices.map((p) => {
    const d = new Date(p.start)
    const cls = ['b', p.charge ? 'charge' : '', p.price < 0 ? 'neg' : ''].join(' ').trim()
    const height = Math.max(4, ((p.price - floor) / (hi - floor)) * 100)
    const tick = d.getMinutes() === 0 && d.getHours() % 4 === 0
      ? el('span', { class: 'tick dim' }, clock(p.start).slice(0, 2)) : null
    return el('div', { class: 'slot', title: `${clock(p.start)}  ${ct(p.price)}${p.charge ? '  charge' : ''}` },
      el('div', { class: cls, style: { height: `${height}%` } }), tick)
  }))
  const min = prices.reduce((a, b) => (b.price < a.price ? b : a))
  const max = prices.reduce((a, b) => (b.price > a.price ? b : a))
  $('legend').replaceChildren(
    `min ${ct(min.price)} @ ${clock(min.start)} · max ${ct(max.price)} @ ${clock(max.start)} · `,
    el('span', { class: 'key' }), ' planned charge')
}

function render(s) {
  $('version').textContent = `v${s.version}`
  const online = $('online')
  online.textContent = s.online ? '● ONLINE' : '● OFFLINE'
  online.className = s.online ? '' : 'bad'
  $('evaluated').textContent = `eval ${clock(s.evaluated_at)}`
  renderBattery(s)
  renderSavings(s)
  renderNow(s)
  renderPlan(s)
  renderPrices(s)
  $('loading').hidden = true
  $('main').hidden = false
  $('main').classList.toggle('stale', !s.online)
}

function showError(message) {
  const error = $('error')
  error.hidden = !message
  error.textContent = message ? `!! ${message}${last ? ' - showing the last known data' : ''}` : ''
  $('main').classList.toggle('stale', !!message || (last && !last.online))
  if (message && !last) $('loading').hidden = true
}

// ---- loop -------------------------------------------------------------------

function schedule() {
  clearTimeout(pollTimer)
  const next = last && last.next_evaluation
  const delay = next ? next + 1000 - Date.now() : FALLBACK_POLL_MS
  const wait = Math.max(MIN_POLL_MS, Math.min(delay, 10 * 60000))
  nextPollAt = Date.now() + wait
  pollTimer = setTimeout(load, wait)
}

async function load() {
  try {
    last = await call('status')
    render(last)
    showError(null)
    $('token').hidden = true
  } catch (e) {
    if (e instanceof Unauthorized) {
      $('token').hidden = false
      $('loading').hidden = true
    } else {
      showError(`batcontrol unreachable: ${e.message}`)
    }
  } finally {
    schedule()
  }
}

async function manual(action) {
  const button = $('manual')
  button.disabled = true
  try {
    if (action === 'cancel') await call('manual-charge', 'DELETE')
    else await call('manual-charge', 'POST', { minutes: 60 })
    // The control loop wakes up and applies it within a second or two.
    await new Promise((r) => setTimeout(r, 1500))
  } catch (e) {
    if (e instanceof Unauthorized) $('token').hidden = false
    else showError(`manual charge failed: ${e.message}`)
  } finally {
    button.disabled = false
    load()
  }
}

document.addEventListener('DOMContentLoaded', () => {
  $('manual').addEventListener('click', (e) => manual(e.currentTarget.dataset.action))
  $('token').addEventListener('submit', (e) => {
    e.preventDefault()
    setToken($('token-input').value.trim())
    $('token-input').value = ''
    load()
  })
  setInterval(() => {
    $('countdown').textContent = `↻ ${Math.max(0, Math.ceil((nextPollAt - Date.now()) / 1000))}s`
  }, 1000)
  load()
})

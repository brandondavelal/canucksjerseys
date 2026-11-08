/* Inventory = the Google Sheet (columns A-M). This file turns sheet rows into the products the site and the admin use.
   - data.js holds a snapshot of the rows (first paint / offline fallback)
   - loadInventoryLive() fetches the live sheet; the site swaps it in when it arrives
   - order.js (GALLERY_ORDER) is the manual order saved from collection-admin.html; it is the only thing the admin edits */

var SHEET_ID = '1SUNxAUAoEavaTudeLMIOMZmNqP95UN4pE5inHnIwwhI';
/* only columns A-M and U (State: "Sell" = for sale) are requested, so nothing else in the sheet is ever sent to the page */
var SHEET_BASE = 'https://docs.google.com/spreadsheets/d/' + SHEET_ID + '/export?format=csv&gid=0&range=';
var SHEET_URL = SHEET_BASE + 'A:M', SHEET_STATE_URL = SHEET_BASE + 'U:U';

/* a listing's own photos come from images.js (written by the local CMS); until it has any it shows five placeholders */
var LISTING_IMAGES = typeof GALLERY_IMAGES !== 'undefined' ? GALLERY_IMAGES : {};
var PLACEHOLDER_IMAGES = [1, 2, 3, 4, 5].map(function(i) { return 'images/placeholder-' + i + '.svg'; });

/* U State (kept as a 14th value on each row): "Sell" puts the jersey in the For Sale filter */
/* A Player | B # | C Team | D Style | E Year | F Brand | G Model | H Classification | I Condition | J Size | K Designation | L Patches | M Notes */
function parseCsv(text) {
  var rows = [], row = [], cell = '', q = false, i = 0, c;
  text = String(text || '').replace(/^﻿/, '');
  for (; i < text.length; i++) {
    c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function slugify(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''); }

function teamCategory(team) {
  var t = String(team || '');
  return /canucks/i.test(t) ? 'canucks' : /canada/i.test(t) ? 'canada' : 'other';
}

function rowsToProducts(rows) {
  var seen = {}, out = [];
  rows.forEach(function(r) {
    var c = []; for (var k = 0; k < 14; k++) c[k] = String(r[k] == null ? '' : r[k]).replace(/\s+/g, ' ').trim();
    if (!c[0] || /^player$/i.test(c[0]) || /^total$/i.test(c[0])) return; /* header and totals rows */
    var patches = (c[11] === '-' ? '' : c[11]).split(/\s*,\s*/).filter(Boolean);
    var id = slugify([c[0], c[1], c[3], c[4], c[9]].join(' ')) || 'jersey';
    if (seen[id]) { seen[id]++; id += '-' + seen[id]; } else seen[id] = 1;
    out.push({
      id: id, player: c[0], number: c[1], team: c[2], title: c[3], year: c[4], manufacturer: c[5], model: c[6],
      jerseyType: c[7], condition: c[8], size: c[9], designation: c[10], patches: patches, notes: c[12] === '-' ? '' : c[12],
      onSale: /^sell$/i.test(c[13]), category: teamCategory(c[2]), images: (LISTING_IMAGES[id] && LISTING_IMAGES[id].length) ? LISTING_IMAGES[id].slice() : PLACEHOLDER_IMAGES.slice(), hasPhotos: !!(LISTING_IMAGES[id] && LISTING_IMAGES[id].length)
    });
  });
  return out;
}

/* products in the saved manual order; anything not in the order yet follows in sheet order */
function applyOrder(products, order) {
  if (!order || !order.length) return products.slice();
  var pos = {}; order.forEach(function(id, i) { pos[id] = i; });
  return products.map(function(p, i) { return { p: p, i: i }; }).sort(function(a, b) {
    var pa = a.p.id in pos ? pos[a.p.id] : 1e6 + a.i, pb = b.p.id in pos ? pos[b.p.id] : 1e6 + b.i;
    return pa - pb;
  }).map(function(x) { return x.p; });
}

function fetchCsv(url, timeoutMs) {
  var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  var timer = ctl ? setTimeout(function() { ctl.abort(); }, timeoutMs || 8000) : 0;
  return fetch(url, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
    .then(function(r) { if (!r.ok) throw new Error('sheet ' + r.status); return r.text(); })
    .then(function(t) { clearTimeout(timer); return parseCsv(t); });
}

function loadInventoryLive(timeoutMs) {
  return Promise.all([fetchCsv(SHEET_URL, timeoutMs), fetchCsv(SHEET_STATE_URL, timeoutMs).catch(function() { return []; })]).then(function(res) {
    var rows = res[0], state = res[1];
    rows.forEach(function(r, i) { while (r.length < 13) r.push(''); r[13] = state[i] ? state[i][0] : ''; });
    var list = rowsToProducts(rows);
    if (!list.length) throw new Error('empty sheet');
    return list;
  });
}

var SNAPSHOT_ROWS = typeof GALLERY_ROWS !== 'undefined' ? GALLERY_ROWS : [];

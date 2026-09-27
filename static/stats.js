// cachest stats page.
//
// Cache entries arrive as JSON in a <script type="application/json"> block, so the
// server never has to hand-write JavaScript and Jinja's tojson filter escapes
// "</script>" in cached values. Every value that reaches the DOM goes through
// textContent — cached values are upstream response bodies, and some upstreams
// (news headlines, scraped HTML) are not trustworthy markup.

const entriesEl = document.getElementById('cache-entries');
const entries = JSON.parse(entriesEl.textContent);

let sortDesc = true;
let filterText = '';

function matches(entry) {
  if (!filterText) return true;
  const needle = filterText.toLowerCase();
  return entry.ticker.toLowerCase().includes(needle)
    || entry.route.toLowerCase().includes(needle);
}

function renderCacheTable() {
  const rows = entries.filter(matches);
  rows.sort((a, b) => (sortDesc ? b.ts - a.ts : a.ts - b.ts));

  const tbody = document.getElementById('cache-tbody');
  tbody.replaceChildren();
  for (const entry of rows) {
    const tr = document.createElement('tr');
    for (const [className, text] of [
      ['cell-ticker', entry.ticker],
      ['cell-route', entry.route],
      ['cell-date', new Date(entry.ts * 1000).toLocaleString()],
      ['cell-value', entry.value],
    ]) {
      const td = document.createElement('td');
      td.className = className;
      td.textContent = text;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }

  document.getElementById('entry-count').textContent = `(${rows.length} entries)`;

  const btn = document.getElementById('invalidate-btn');
  btn.disabled = !filterText || rows.length === 0;
  btn.textContent = filterText && rows.length > 0
    ? `Invalidate ${rows.length} entr${rows.length === 1 ? 'y' : 'ies'}`
    : 'Invalidate';
}

function setSortDesc(desc) {
  sortDesc = desc;
  document.getElementById('sort-desc').classList.toggle('active', desc);
  document.getElementById('sort-asc').classList.toggle('active', !desc);
  renderCacheTable();
}

async function post(url, body) {
  const opts = { method: 'POST' };
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`);
  return resp.json();
}

document.getElementById('invalidate-btn').addEventListener('click', async () => {
  if (!confirm('Invalidate the matching cache entries? They will be re-fetched on demand.')) return;
  // Exact keys, not a prefix pattern: an entry can belong to a route whose key has
  // more segments than the route name (ohlcv:AAPL:start:end), which a pattern built
  // from the ticker alone would never match.
  const keys = entries.filter(matches).map((e) => e.key);
  const btn = document.getElementById('invalidate-btn');
  btn.disabled = true;
  try {
    await post('/stats/invalidate-keys', { keys });
    const removed = new Set(keys);
    for (let i = entries.length - 1; i >= 0; i--) {
      if (removed.has(entries[i].key)) entries.splice(i, 1);
    }
    renderCacheTable();
  } catch (e) {
    alert(`Invalidate failed: ${e.message}`);
    renderCacheTable();
  }
});

document.getElementById('reset-stats').addEventListener('click', async () => {
  if (!confirm('Reset all statistics? This cannot be undone.')) return;
  await post('/stats/reset');
  location.reload();
});

for (const btn of document.querySelectorAll('[data-reset-prefix]')) {
  btn.addEventListener('click', async () => {
    const { resetPrefix, resetLabel } = btn.dataset;
    if (!confirm(`Delete all cached keys for "${resetPrefix}"? This cannot be undone.`)) return;
    try {
      await post(`/stats/reset-cache/${encodeURIComponent(resetPrefix)}`);
      location.reload();
    } catch (e) {
      alert(`Reset failed: ${e.message}`);
    }
  });
}

document.getElementById('sort-desc').addEventListener('click', () => setSortDesc(true));
document.getElementById('sort-asc').addEventListener('click', () => setSortDesc(false));
document.getElementById('cache-filter').addEventListener('input', (e) => {
  filterText = e.target.value;
  renderCacheTable();
});

renderCacheTable();

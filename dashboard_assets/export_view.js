// "Export current view": turns exactly what the dashboard shows (its
// filtered Overview rows, in their on-screen order, e.g. after sorting by
// members) into reports. Inlined into the dashboard by
// generate_vitality_report.py after report_export.js, which turns the
// `.group-page`s rendered here into PDFs (downloadAllPdfs/downloadPagePdf).
//
// Flow: visible `.ou-row`s (data-spoid) -> records from #export-data (one per
// OU, already evaluated in Python: n name, id SPO ID, t type key, u
// university, s/sd society code/name, se section, co council, m/mm members
// and minimum, e/em counted events and minimum, mo/eo met flags, ch chair,
// r2 second role, cn second role filled, rq requirements met 0-3, ok full
// vitality, miss [missing requirements]) -> split by the dialog's "one
// report per" -> one light `.group-page` per group in #export-pages
// (off-screen; print shows only it) -> PDF ZIP / CSV / print.

(function () {
  const DATA = JSON.parse(document.getElementById('export-data').textContent);
  const BY_ID = {};
  DATA.ous.forEach(o => { BY_ID[o.id.toLowerCase()] = o; });
  const TYPES = { branch: 'Student Branches', chapter: 'Chapters', ag: 'Affinity Groups' };
  const TYPE_NAME = { branch: 'Student Branch', chapter: 'Student Branch Chapter', ag: 'Affinity Group' };
  const STATUS = {
    met: 'Meeting full vitality', notmet: 'Not meeting full vitality',
    one: 'Missing one requirement', two: 'Missing two or more requirements',
  };
  const GROUP = { none: 'single report', branch: 'Student Branch', section: 'Section', council: 'Council', society: 'Society' };
  const NO = { section: 'No Section', council: 'No Council', society: 'No Society (Student Branches)' };

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const famKey = o => o.u || o.n;
  const slug = s => s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const fileSafe = s => s.replace(/[\\/:*?"<>|\x00-\x1f]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/\.+$/, '').slice(0, 150) || 'report';
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const SOCIETY_NAMES = {};
  DATA.ous.forEach(o => { if (o.s) SOCIETY_NAMES[o.s] = o.sd || o.s; });

  // ---------- the current view ----------
  // Overview rows only (the Quick Wins tab repeats some OUs), in DOM order,
  // which is the on-screen order: types in table order, each table as sorted.
  function viewRecords() {
    return [...document.querySelectorAll('#tab-overview .ou-section:not([hidden]) .ou-row')]
      .filter(r => r.style.display !== 'none')
      .map(r => BY_ID[r.dataset.spoid])
      .filter(Boolean);
  }

  const val = id => { const el = $(id); return el ? el.value : ''; };
  const label = id => { const el = $(id); return el && el.value ? el.selectedOptions[0].textContent : ''; };
  // `group`: the dimension the export is split by, left out (each page's
  // title already says it).
  function filterLine(group) {
    const bits = [];
    const types = [...document.querySelectorAll('#type-filter input')].filter(b => b.checked).map(b => b.value);
    if (types.length !== 3) bits.push(types.map(t => TYPES[t]).join(', '));
    if (STATUS[val('status-filter')]) bits.push(STATUS[val('status-filter')]);
    if (val('council-filter') && group !== 'council') bits.push(`Council: ${label('council-filter')}`);
    if (val('section-filter') && group !== 'section') bits.push(`Section: ${label('section-filter')}`);
    if (val('university-filter') && group !== 'branch') bits.push(`University: ${label('university-filter')}`);
    if (val('society-filter') && group !== 'society') bits.push(`Society: ${label('society-filter')}`);
    if (val('search').trim()) bits.push(`Search: "${val('search').trim()}"`);
    return bits;
  }

  function options() {
    const g = document.querySelector('input[name=export-group]:checked');
    return { group: g ? g.value : 'none', nest: $('export-nest').checked };
  }

  // ---------- grouping (keeps the view's order inside each group) ----------
  function groupKey(o, group) {
    if (group === 'branch') return famKey(o);
    if (group === 'section') return o.se || NO.section;
    if (group === 'council') return o.co || NO.council;
    if (group === 'society') return o.s || NO.society;
    return 'all';
  }

  // Families stay together (in order of first appearance), each Student
  // Branch first, then its Chapters/AGs in view order.
  function nestOrder(ous) {
    const fams = new Map();
    ous.forEach(o => { if (!fams.has(famKey(o))) fams.set(famKey(o), []); fams.get(famKey(o)).push(o); });
    return [...fams.values()].flatMap(list => [...list.filter(o => o.t === 'branch'), ...list.filter(o => o.t !== 'branch')]);
  }

  function mostCommon(values) {
    const counts = {};
    values.filter(Boolean).forEach(v => { counts[v] = (counts[v] || 0) + 1; });
    return Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b))[0] || '';
  }

  function makeGroups(list, opts) {
    const map = new Map();
    list.forEach(o => {
      const k = groupKey(o, opts.group);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(o);
    });
    const isNo = k => Object.values(NO).includes(k);
    const keys = [...map.keys()].sort((a, b) => (isNo(a) - isNo(b)) || a.localeCompare(b));
    const groups = keys.map((k, i) => ({ key: k, ous: map.get(k), id: `export-g${i}` }));
    const sectionsSpanned = new Set(groups.map(g => mostCommon(g.ous.map(o => o.se))).filter(Boolean));
    const taken = new Set();
    groups.forEach(g => {
      if (opts.nest && opts.group !== 'branch') g.ous = nestOrder(g.ous);
      if (opts.group === 'branch') {
        g.ous = nestOrder(g.ous);
        g.title = g.key;
        const branches = g.ous.filter(o => o.t === 'branch');
        g.section = mostCommon((branches.length ? branches : g.ous).map(o => o.se));
        const named = DATA.ous.filter(o => o.t === 'branch' && famKey(o) === g.key);  // even if branches are filtered out
        g.subtitle = [named.map(b => `${b.n} (${b.id})`).join(', ') || 'No Student Branch on record', g.section].filter(Boolean).join(' · ');
        g.file = (named.length ? named.map(b => b.id).join('+') + ' - ' : '') + g.key;
        g.folder = sectionsSpanned.size > 1 ? slug(g.section || 'no-section') : '';
      } else if (opts.group === 'society') {
        const name = SOCIETY_NAMES[g.key] || g.key;
        g.title = g.key === NO.society ? g.key : name;
        g.subtitle = g.key !== NO.society && name !== g.key ? `${g.key} · ${DATA.scope}` : DATA.scope;
        g.file = g.key === NO.society ? 'No Society' : (name !== g.key ? `${g.key} - ${name}` : g.key);
        g.folder = '';
      } else if (opts.group === 'section' || opts.group === 'council') {
        g.title = g.key;
        g.subtitle = opts.group === 'section' ? mostCommon(g.ous.map(o => o.co)) : '';
        g.file = g.key;
        g.folder = '';
      } else {
        g.title = val('section-filter') || DATA.scope;
        g.subtitle = label('university-filter');
        g.file = `Vitality report - ${g.title}`;
        g.folder = '';
      }
      let name = fileSafe(g.file), n = 2;
      while (taken.has(g.folder + '/' + name.toLowerCase())) name = `${fileSafe(g.file)} (${n++})`;
      taken.add(g.folder + '/' + name.toLowerCase());
      g.file = name;
    });
    return groups;
  }

  // ---------- page rendering ----------
  const ratio = (v, min, ok) => `<span class="${ok ? 'ok' : 'no'}">${v}/${min}</span>`;
  const yesNo = ok => `<span class="${ok ? 'ok' : 'no'}">${ok ? 'Yes' : 'No'}</span>`;
  const reqCell = o => `<td class="num" style="color:${DATA.colors[o.rq]}">${o.rq}/3</td>`;

  function stats(ous) {
    const met = ous.filter(o => o.ok).length;
    const levels = [3, 2, 1, 0].map(l => [l, ous.filter(o => o.rq === l).length]);
    const max = Math.max(1, ...levels.map(x => x[1]));
    const LABEL = { 3: 'Full', 2: 'Partial', 1: 'Minimal', 0: 'None' };
    // Chapter and Affinity Group members are also Branch members, so summing every OU would double count.
    const branches = ous.filter(o => o.t === 'branch');
    const membersStat = branches.length ? ['Student Branch Members', branches.reduce((s, o) => s + o.m, 0)]
      : ous.length === 1 ? ['Members', ous[0].m] : null;
    return `<div class="stat-row">
        <div class="stat"><div class="stat-label">OUs</div><div class="stat-value">${ous.length}</div></div>
        <div class="stat"><div class="stat-label">Meeting full vitality</div><div class="stat-value good">${met}/${ous.length}</div></div>
        ${membersStat ? `<div class="stat"><div class="stat-label">${membersStat[0]}</div><div class="stat-value">${membersStat[1]}</div></div>` : ''}
      </div>
      <div class="bar-chart">${levels.map(([l, n]) => `<div class="bar-row"><div class="bar-label">${LABEL[l]} (${l}/3)</div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.round((n / max) * 100)}%;background:${DATA.colors[l]}"></div></div>
        <div class="bar-value">${n}</div></div>`).join('')}</div>`;
  }

  function secondRoleHeader(ous) {
    const hasB = ous.some(o => o.t === 'branch'), hasOther = ous.some(o => o.t !== 'branch');
    return hasB && hasOther ? 'Counselor / Advisor' : hasB ? 'Counselor' : 'Advisor';
  }

  function ouTable(ous, { nest, showUniversity, showSection }) {
    const showType = new Set(ous.map(o => o.t)).size > 1;
    const head = ['<th>Unit</th>', showType ? '<th>Type</th>' : '', showUniversity ? '<th>University</th>' : '',
      showSection ? '<th>Section</th>' : '', '<th>SPO ID</th>', '<th class="num">Members</th>', '<th class="num">Events</th>',
      '<th>Chair</th>', `<th>${secondRoleHeader(ous)}</th>`, '<th class="num">Req.</th>', '<th>Missing</th>'].join('');
    const ncol = (head.match(/<th/g) || []).length;
    const row = (o, child) => `<tr${child ? ' class="child"' : ''}><td>${esc(o.n)}</td>` +
      (showType ? `<td>${TYPE_NAME[o.t]}</td>` : '') + (showUniversity ? `<td>${esc(o.u)}</td>` : '') +
      (showSection ? `<td>${esc(o.se)}</td>` : '') + `<td class="mono">${esc(o.id)}</td>` +
      `<td class="num">${ratio(o.m, o.mm, o.mo)}</td><td class="num">${ratio(o.e, o.em, o.eo)}</td>` +
      `<td>${yesNo(o.ch)}</td><td>${yesNo(o.cn)}</td>${reqCell(o)}<td class="missing">${esc(o.miss.join('; '))}</td></tr>`;
    let body = '';
    if (nest) {
      let fam = null;
      ous.forEach(o => {
        if (famKey(o) !== fam) { fam = famKey(o); body += `<tr class="family"><th colspan="${ncol}">${esc(fam)}</th></tr>`; }
        body += row(o, o.t !== 'branch');
      });
    } else body = ous.map(o => row(o, false)).join('');
    return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  // One line per university: the branch's result and how its Chapters / AGs do.
  function branchSummary(ous) {
    const fams = new Map();
    ous.forEach(o => { if (!fams.has(famKey(o))) fams.set(famKey(o), []); fams.get(famKey(o)).push(o); });
    if (fams.size < 2) return '';
    const show = t => ous.some(o => o.t === t);
    const metCell = list => (list.length
      ? `<td class="num"><span class="${list.every(o => o.ok) ? 'ok' : 'no'}">${list.filter(o => o.ok).length}/${list.length}</span></td>`
      : '<td class="num muted">none</td>');
    const rows = [...fams].map(([uni, list]) => {
      const b = list.filter(o => o.t === 'branch');
      let cells = `<td>${esc(uni)}</td>`;
      if (show('branch')) {
        cells += b.length ? `<td class="num" style="color:${DATA.colors[Math.min(...b.map(x => x.rq))]}">${Math.min(...b.map(x => x.rq))}/3</td>`
          + `<td class="missing">${esc(b.flatMap(x => x.miss).join('; '))}</td>`
          : '<td class="num muted">none</td><td></td>';
      }
      if (show('chapter')) cells += metCell(list.filter(o => o.t === 'chapter'));
      if (show('ag')) cells += metCell(list.filter(o => o.t === 'ag'));
      return `<tr>${cells}</tr>`;
    }).join('');
    const head = '<th>University</th>' + (show('branch') ? '<th class="num">Branch req.</th><th>Missing at the Student Branch</th>' : '')
      + (show('chapter') ? '<th class="num">Chapters met</th>' : '') + (show('ag') ? '<th class="num">Affinity Groups met</th>' : '');
    return `<h2>Student Branches <span class="muted">${plural(fams.size, 'university', 'universities')}</span></h2>
      <table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
  }

  function branchPage(g) {
    const branches = g.ous.filter(o => o.t === 'branch');
    const children = g.ous.filter(o => o.t !== 'branch');
    let out = '';
    branches.forEach(b => {
      out += `<h2>Student Branch: ${esc(b.n)}</h2><div class="checklist">
        <div class="check"><div class="check-label">Members (min ${b.mm})</div><div class="check-value">${ratio(b.m, b.mm, b.mo)}</div></div>
        <div class="check"><div class="check-label">Reported events (min ${b.em})</div><div class="check-value">${ratio(b.e, b.em, b.eo)}</div></div>
        <div class="check"><div class="check-label">Chair</div><div class="check-value">${yesNo(b.ch)}</div></div>
        <div class="check"><div class="check-label">${esc(b.r2)}</div><div class="check-value">${yesNo(b.cn)}</div></div>
        <div class="check"><div class="check-label">Status</div><div class="check-value">${b.ok ? '<span class="ok">Meets full vitality</span>' : `<span class="no">Not met (${b.rq}/3)</span>`}</div></div>
      </div>${b.miss.length ? `<p class="note">Missing: <span class="no">${esc(b.miss.join('; '))}</span></p>` : ''}`;
    });
    if (children.length) {
      const what = [...new Set(children.map(o => o.t))].map(t => TYPES[t]).join(' & ');
      out += `<h2>${what} <span class="muted">${children.filter(o => o.ok).length}/${children.length} meeting full vitality</span></h2>`
        + ouTable(children, { nest: false, showUniversity: false, showSection: false });
    }
    return out;
  }

  function renderPage(g, opts, filters) {
    const multiSection = new Set(g.ous.map(o => o.se).filter(Boolean)).size > 1;
    let body;
    if (opts.group === 'branch') body = branchPage(g);
    else {
      body = (opts.nest ? branchSummary(g.ous) : '') + `<h2>${opts.nest ? 'Detail by Student Branch' : 'OUs'}</h2>`
        // A Student Branch's name already says its university.
        + ouTable(g.ous, { nest: opts.nest, showUniversity: !opts.nest && g.ous.some(o => o.t !== 'branch'), showSection: multiSection && opts.group !== 'section' });
    }
    const note = filters.length ? `Includes only: ${filters.join(' · ')}` : '';
    return `<section class="group-page" id="${g.id}" data-filename="${esc(g.file)}"${g.folder ? ` data-folder="${esc(g.folder)}"` : ''}>
      <h1>${esc(g.title)}</h1>
      ${g.subtitle ? `<p class="context">${esc(g.subtitle)}</p>` : ''}
      <p class="subtitle">IEEE Student OU Vitality Report, generated ${esc(DATA.generated)}</p>
      ${note ? `<p class="context type-note">${esc(note)}</p>` : ''}
      ${stats(g.ous)}
      ${body}
    </section>`;
  }

  // Renders the current view into #export-pages; returns the groups.
  function render(opts) {
    opts = opts || options();
    const groups = makeGroups(viewRecords(), opts);
    const filters = filterLine(opts.group);
    $('export-pages').innerHTML = groups.map(g => renderPage(g, opts, filters)).join('');
    return groups;
  }

  // ---------- dialog ----------
  function refreshDialog() {
    const list = viewRecords();
    const opts = options();
    const groups = list.length ? makeGroups(list, opts) : [];
    const filters = filterLine();
    $('export-summary').innerHTML = list.length
      ? `<strong>${plural(list.length, 'OU', 'OUs')}</strong>, ${list.filter(o => o.ok).length} meeting full vitality`
        + (filters.length ? `<br><span class="muted">${esc(filters.join(' · '))}</span>` : '<br><span class="muted">No filters: everything on this dashboard</span>')
      : '<strong>No OUs in the current view.</strong> Change the filters first.';
    $('export-nest-opt').hidden = opts.group === 'branch';
    $('export-count').textContent = groups.length > 1 ? `${groups.length} reports, one per ${GROUP[opts.group].toLowerCase()}` : (groups.length ? '1 report' : '');
    const pdf = $('download-all-pdfs');
    pdf.textContent = groups.length > 1 ? `Download ${groups.length} PDFs (.zip)` : 'Download PDF';
    [pdf, $('export-csv'), $('export-print')].forEach(b => { b.disabled = !groups.length; });
    $('export-hint').textContent = groups.length > 1
      ? `One PDF per ${GROUP[opts.group].toLowerCase()}, named ${opts.group === 'branch' ? 'by SPO ID and university' : 'after it'}${groups.some(g => g.folder) ? ', in one folder per Section' : ''}. Rows keep the order shown on the dashboard.`
      : 'Rows keep the order shown on the dashboard.';
  }

  function baseName(opts) {
    const bits = ['vitality', slug(DATA.scope), opts.group === 'none' ? 'view' : `by-${opts.group}`];
    const types = [...document.querySelectorAll('#type-filter input')].filter(b => b.checked).map(b => b.value);
    if (types.length !== 3) bits.push(types.join('-'));
    ['status-filter', 'council-filter', 'section-filter', 'university-filter', 'society-filter'].forEach(id => { if (val(id)) bits.push(slug(val(id))); });
    return bits.filter(Boolean).join('_') + '_' + DATA.generated;
  }

  $('export-view-btn').addEventListener('click', () => { refreshDialog(); $('export-dialog').showModal(); });
  $('export-dialog').addEventListener('change', refreshDialog);

  $('download-all-pdfs').addEventListener('click', e => {
    const opts = options();
    const groups = render(opts);
    if (groups.length === 1) window.downloadPagePdf(groups[0].id);
    else if (groups.length) window.downloadAllPdfs(baseName(opts) + '.zip', e.currentTarget);
  });

  $('export-print').addEventListener('click', () => {
    if (!render().length) return;
    $('export-dialog').close();
    document.body.classList.add('printing-export');
    window.print();
  });
  window.addEventListener('afterprint', () => document.body.classList.remove('printing-export'));

  $('export-csv').addEventListener('click', () => {
    const opts = options();
    const grouped = opts.group !== 'none';
    const groups = makeGroups(viewRecords(), opts);
    const cols = [...(grouped ? [GROUP[opts.group]] : []), 'Unit Name', 'SPO ID', 'Unit Type', 'University', 'Society', 'Section', 'Council',
      'Member Count', 'Members Required', 'Events (Reported)', 'Events Required', 'Chair', 'Counselor / Advisor',
      'Requirements Met', 'Overall Vitality', 'Missing'];
    const cell = v => { const s = String(v == null ? '' : v); return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const lines = [cols.map(cell).join(',')];
    groups.forEach(g => g.ous.forEach(o => {
      lines.push([...(grouped ? [g.title] : []), o.n, o.id, TYPE_NAME[o.t], o.u, o.s, o.se, o.co, o.m, o.mm, o.e, o.em,
        o.ch ? 'Yes' : 'No', o.cn ? 'Yes' : 'No', `${o.rq}/3`, o.ok ? 'Met' : 'Not Met', o.miss.join('; ')].map(cell).join(','));
    }));
    const blob = new Blob(['﻿' + lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = baseName(opts) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  // For automations/export_report_pdfs.py and tests.
  window.__exportView = { render, viewRecords, makeGroups };
})();

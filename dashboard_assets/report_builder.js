// Report builder: one page for every printable report and export.
// Inlined into report_builder.html by generate_vitality_report.py
// (build_report_builder), after report_export.js, which turns the
// `.group-page`s rendered here into PDFs (downloadAllPdfs/downloadPagePdf).
//
// Flow: controls -> state (mirrored in the URL) -> filter OUs -> split into
// groups -> render one .group-page per group (preview, print and PDF all use
// the same markup) -> export. Data is the #builder-data JSON: one record per
// OU, already evaluated in Python (n name, id SPO ID, t type key, u
// university, s/sd society code/name, se section, co council, m/mm members
// and minimum, e/em counted events and minimum, mo/eo met flags, ch chair,
// r2 second role, cn second role filled, rq requirements met 0-3, ok full
// vitality, miss [missing requirements]).

(function () {
  const DATA = JSON.parse(document.getElementById('builder-data').textContent);
  const OUS = DATA.ous;
  const TYPES = { branch: 'Student Branches', chapter: 'Chapters', ag: 'Affinity Groups' };
  const TYPE_NAME = { branch: 'Student Branch', chapter: 'Student Branch Chapter', ag: 'Affinity Group' };
  const TYPE_ORDER = { branch: 0, chapter: 1, ag: 2 };
  const STATUS = {
    all: '', met: 'Meeting full vitality', notmet: 'Not meeting full vitality',
    one: 'Missing one requirement', two: 'Missing two or more requirements',
  };
  const GROUP = { none: 'Single report', branch: 'Student Branch', section: 'Section', council: 'Council', society: 'Society' };
  const NO = { section: 'No Section', council: 'No Council', society: 'No Society (Student Branches)' };

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const uniq = list => [...new Set(list.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const famKey = o => o.u || o.n;
  const slug = s => s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const fileSafe = s => s.replace(/[\\/:*?"<>|\x00-\x1f]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/\.+$/, '').slice(0, 150) || 'report';
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  const ALL_COUNCILS = uniq(OUS.map(o => o.co));
  const ALL_SECTIONS = uniq(OUS.map(o => o.se));
  const SOCIETY_NAMES = {};
  OUS.forEach(o => { if (o.s) SOCIETY_NAMES[o.s] = o.sd || o.s; });

  // ---------- state <-> controls <-> URL ----------
  const radios = name => [...document.querySelectorAll(`input[name=${name}]`)];
  const checked = name => (radios(name).find(r => r.checked) || {}).value;

  function readControls() {
    return {
      council: $('f-council').value,
      section: $('f-section').value,
      university: $('f-university').value,
      society: $('f-society').value,
      q: $('f-q').value.trim(),
      types: radios('types').filter(b => b.checked).map(b => b.value),
      status: checked('status') || 'all',
      group: checked('group') || 'none',
      nest: $('f-nest').checked,
    };
  }

  function writeControls(st) {
    // Selects are re-filled by cascade() before their value is set.
    radios('types').forEach(b => { b.checked = st.types.includes(b.value); });
    radios('status').forEach(r => { r.checked = r.value === st.status; });
    radios('group').forEach(r => { r.checked = r.value === st.group; });
    $('f-nest').checked = st.nest;
    $('f-q').value = st.q || '';
    cascade(st);
  }

  function stateFromUrl() {
    const p = new URLSearchParams(location.search);
    const types = (p.get('types') || '').split(',').filter(t => TYPES[t]);
    return {
      council: p.get('council') || '', section: p.get('section') || '',
      university: p.get('university') || '', society: p.get('society') || '', q: p.get('q') || '',
      types: types.length ? types : Object.keys(TYPES),
      status: STATUS[p.get('status')] !== undefined ? p.get('status') : 'all',
      group: GROUP[p.get('group')] ? p.get('group') : 'none',
      nest: p.get('nest') !== '0',
    };
  }

  function syncUrl(st) {
    const p = new URLSearchParams();
    ['council', 'section', 'university', 'society', 'q'].forEach(k => { if (st[k]) p.set(k, st[k]); });
    if (st.types.length !== 3) p.set('types', st.types.join(','));
    if (st.status !== 'all') p.set('status', st.status);
    if (st.group !== 'none') p.set('group', st.group);
    if (!st.nest) p.set('nest', '0');
    try { history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p : '')); } catch (e) { /* file:// */ }
  }

  // Council -> Section -> university options narrow to what the level above allows.
  function fillSelect(id, values, allLabel, current, labelOf) {
    const sel = $(id);
    sel.innerHTML = `<option value="">${esc(allLabel)}</option>` +
      values.map(v => `<option value="${esc(v)}">${esc(labelOf ? labelOf(v) : v)}</option>`).join('');
    // Exact match, else case/accent-insensitive: the dashboard passes its
    // own (lowercased) filter values, e.g. ?university=universidad de los andes.
    const norm = v => (v || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
    sel.value = values.includes(current) ? current : (values.find(v => norm(v) === norm(current)) || '');
  }
  function cascade(st) {
    fillSelect('f-council', ALL_COUNCILS, 'All councils', st.council);
    const inCouncil = OUS.filter(o => !$('f-council').value || o.co === $('f-council').value);
    fillSelect('f-section', uniq(inCouncil.map(o => o.se)), 'All sections', st.section);
    const inSection = inCouncil.filter(o => !$('f-section').value || o.se === $('f-section').value);
    fillSelect('f-university', uniq(inSection.map(famKey)), 'All Student Branches', st.university);
    const inUni = inSection.filter(o => !$('f-university').value || famKey(o) === $('f-university').value);
    fillSelect('f-society', uniq(inUni.map(o => o.s)), 'All societies', st.society,
      code => (SOCIETY_NAMES[code] && SOCIETY_NAMES[code] !== code ? `${code}: ${SOCIETY_NAMES[code]}` : code));
  }

  // ---------- selection ----------
  function matches(o, st) {
    if (st.council && o.co !== st.council) return false;
    if (st.section && o.se !== st.section) return false;
    if (st.university && famKey(o) !== st.university) return false;
    if (st.society && o.s !== st.society) return false;
    if (!st.types.includes(o.t)) return false;
    if (st.status === 'met' && !o.ok) return false;
    if (st.status === 'notmet' && o.ok) return false;
    if (st.status === 'one' && o.rq !== 2) return false;
    if (st.status === 'two' && o.rq > 1) return false;
    if (st.q) {
      const q = st.q.toLowerCase();
      if (![o.n, o.id, o.u, o.se, o.s].some(v => (v || '').toLowerCase().includes(q))) return false;
    }
    return true;
  }

  const byFamily = (a, b) => famKey(a).localeCompare(famKey(b)) || TYPE_ORDER[a.t] - TYPE_ORDER[b.t] || a.n.localeCompare(b.n);

  function groupKey(o, group) {
    if (group === 'branch') return famKey(o);
    if (group === 'section') return o.se || NO.section;
    if (group === 'council') return o.co || NO.council;
    if (group === 'society') return o.s || NO.society;
    return 'all';
  }

  function makeGroups(list, st) {
    const map = new Map();
    list.slice().sort(byFamily).forEach(o => {
      const k = groupKey(o, st.group);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(o);
    });
    const isNo = k => Object.values(NO).includes(k);
    const keys = [...map.keys()].sort((a, b) => (isNo(a) - isNo(b)) || a.localeCompare(b));
    const groups = keys.map((k, i) => ({ key: k, ous: map.get(k), id: `g${i}` }));

    // Titles, subtitles, file names (unique per folder) and folders.
    const sectionsSpanned = uniq(groups.map(g => mostCommon(g.ous.map(o => o.se))));
    const taken = new Set();
    groups.forEach(g => {
      const branches = g.ous.filter(o => o.t === 'branch');
      if (st.group === 'branch') {
        g.title = g.key;
        g.section = mostCommon((branches.length ? branches : g.ous).map(o => o.se));
        const named = OUS.filter(o => o.t === 'branch' && famKey(o) === g.key);  // even if branches are filtered out
        g.subtitle = [named.map(b => `${b.n} (${b.id})`).join(', ') || 'No Student Branch on record', g.section].filter(Boolean).join(' · ');
        g.file = (named.length ? named.map(b => b.id).join('+') + ' - ' : '') + g.key;
        g.folder = sectionsSpanned.length > 1 ? slug(g.section || 'no-section') : '';
      } else if (st.group === 'society') {
        g.title = g.key === NO.society ? g.key : (SOCIETY_NAMES[g.key] || g.key);
        g.subtitle = g.key !== NO.society && SOCIETY_NAMES[g.key] !== g.key ? `${g.key} · ${DATA.scope}` : DATA.scope;
        g.file = g.key === NO.society ? 'No Society' : (SOCIETY_NAMES[g.key] !== g.key ? `${g.key} - ${SOCIETY_NAMES[g.key]}` : g.key);
        g.folder = '';
      } else if (st.group === 'section' || st.group === 'council') {
        g.title = g.key;
        g.subtitle = st.group === 'section' ? (mostCommon(g.ous.map(o => o.co)) || '') : '';
        g.file = g.key;
        g.folder = '';
      } else {
        g.title = st.section || st.council || DATA.scope;
        g.subtitle = st.university ? st.university : '';
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

  function mostCommon(values) {
    const counts = {};
    values.filter(Boolean).forEach(v => { counts[v] = (counts[v] || 0) + 1; });
    return Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b))[0] || '';
  }

  function filterLine(st) {
    const bits = [];
    if (st.types.length !== 3) bits.push(st.types.map(t => TYPES[t]).join(', '));
    if (STATUS[st.status]) bits.push(STATUS[st.status]);
    if (st.council && st.group !== 'council') bits.push(`Council: ${st.council}`);
    // The Section is already in a Student Branch page's subtitle / a single report's title.
    if (st.section && !['section', 'none', 'branch'].includes(st.group)) bits.push(`Section: ${st.section}`);
    if (st.university && st.group !== 'branch' && st.group !== 'none') bits.push(`University: ${st.university}`);
    if (st.society && st.group !== 'society') bits.push(`Society: ${SOCIETY_NAMES[st.society] || st.society}`);
    if (st.q) bits.push(`Search: "${st.q}"`);
    return bits.length ? `Includes only: ${bits.join(' · ')}` : '';
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
    return `<div class="stat-row">
        <div class="stat"><div class="stat-label">OUs</div><div class="stat-value">${ous.length}</div></div>
        <div class="stat"><div class="stat-label">Meeting full vitality</div><div class="stat-value good">${met}/${ous.length}</div></div>
        <div class="stat"><div class="stat-label">Total members</div><div class="stat-value">${ous.reduce((s, o) => s + o.m, 0)}</div></div>
      </div>
      <div class="bar-chart">${levels.map(([l, n]) => `<div class="bar-row"><div class="bar-label">${LABEL[l]} (${l}/3)</div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.round((n / max) * 100)}%;background:${DATA.colors[l]}"></div></div>
        <div class="bar-value">${n}</div></div>`).join('')}</div>`;
  }

  function secondRoleHeader(ous) {
    const hasB = ous.some(o => o.t === 'branch'), hasOther = ous.some(o => o.t !== 'branch');
    return hasB && hasOther ? 'Counselor / Advisor' : hasB ? 'Counselor' : 'Advisor';
  }

  // cols: which optional columns to show.
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
  function branchSummary(ous, st) {
    const fams = new Map();
    ous.forEach(o => { if (!fams.has(famKey(o))) fams.set(famKey(o), []); fams.get(famKey(o)).push(o); });
    if (fams.size < 2) return '';
    const show = t => st.types.includes(t) && ous.some(o => o.t === t);
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
    let html = '';
    branches.forEach(b => {
      html += `<h2>Student Branch: ${esc(b.n)}</h2><div class="checklist">
        <div class="check"><div class="check-label">Members (min ${b.mm})</div><div class="check-value">${ratio(b.m, b.mm, b.mo)}</div></div>
        <div class="check"><div class="check-label">Reported events (min ${b.em})</div><div class="check-value">${ratio(b.e, b.em, b.eo)}</div></div>
        <div class="check"><div class="check-label">Chair</div><div class="check-value">${yesNo(b.ch)}</div></div>
        <div class="check"><div class="check-label">${esc(b.r2)}</div><div class="check-value">${yesNo(b.cn)}</div></div>
        <div class="check"><div class="check-label">Status</div><div class="check-value">${b.ok ? '<span class="ok">Meets full vitality</span>' : `<span class="no">Not met (${b.rq}/3)</span>`}</div></div>
      </div>${b.miss.length ? `<p class="note">Missing: <span class="no">${esc(b.miss.join('; '))}</span></p>` : ''}`;
    });
    if (children.length) {
      const label = [...new Set(children.map(o => o.t))].map(t => TYPES[t]).join(' & ');
      html += `<h2>${label} <span class="muted">${children.filter(o => o.ok).length}/${children.length} meeting full vitality</span></h2>`
        + ouTable(children, { nest: false, showUniversity: false, showSection: false });
    }
    return html;
  }

  function renderPage(g, st) {
    const multiSection = new Set(g.ous.map(o => o.se).filter(Boolean)).size > 1;
    let body;
    if (st.group === 'branch') body = branchPage(g);
    else {
      body = (st.nest ? branchSummary(g.ous, st) : '') + `<h2>${st.nest ? 'Detail by Student Branch' : 'OUs'}</h2>`
        // A Student Branch's name already says its university.
        + ouTable(g.ous, { nest: st.nest, showUniversity: !st.nest && g.ous.some(o => o.t !== 'branch'), showSection: multiSection && st.group !== 'section' });
    }
    const filters = filterLine(st);
    return `<section class="group-page" id="${g.id}" data-filename="${esc(g.file)}"${g.folder ? ` data-folder="${esc(g.folder)}"` : ''}>
      <div class="page-toolbar no-print"><button type="button" data-pdf="${g.id}">Download this PDF</button></div>
      <h1>${esc(g.title)}</h1>
      ${g.subtitle ? `<p class="context">${esc(g.subtitle)}</p>` : ''}
      <p class="subtitle">IEEE Student OU Vitality Report, generated ${esc(DATA.generated)}</p>
      ${filters ? `<p class="context type-note">${esc(filters)}</p>` : ''}
      ${stats(g.ous)}
      ${body}
    </section>`;
  }

  // ---------- update ----------
  let current = { groups: [], st: null, list: [] };

  function update() {
    const st = readControls();
    if (!st.types.length) { radios('types')[0].checked = true; return update(); }
    cascade(st);
    Object.assign(st, readControls());  // cascade may have cleared an option that no longer applies
    syncUrl(st);

    $('opt-nest').hidden = st.group === 'branch';
    const list = OUS.filter(o => matches(o, st));
    const groups = list.length ? makeGroups(list, st) : [];
    current = { groups, st, list };

    const met = list.filter(o => o.ok).length;
    $('summary').innerHTML = list.length
      ? `<strong>${plural(groups.length, 'report', 'reports')}</strong> · ${plural(list.length, 'OU', 'OUs')}, ${met} meeting full vitality`
      : '<strong>No OUs match these filters.</strong>';
    const pdf = $('download-all-pdfs');
    pdf.disabled = !groups.length;
    pdf.textContent = groups.length > 1 ? `Download ${groups.length} PDFs (.zip)` : 'Download PDF';
    $('dl-csv').disabled = !list.length;
    $('print').disabled = !groups.length;
    $('pdf-hint').textContent = groups.length > 1
      ? `One PDF per ${GROUP[st.group].toLowerCase()}, named ${st.group === 'branch' ? 'by SPO ID and university' : 'after it'}${groups.some(g => g.folder) ? ', in one folder per Section' : ''}.`
      : '';

    $('toc').innerHTML = groups.map(g => `<li><a href="#${g.id}">${esc(g.title)}</a> <span class="muted">${g.ous.filter(o => o.ok).length}/${g.ous.length} met</span></li>`).join('');
    $('pages').innerHTML = groups.map(g => renderPage(g, st)).join('');
  }

  // ---------- exports ----------
  function zipBase(st) {
    const bits = ['vitality', st.group === 'none' ? 'report' : `by-${st.group}`];
    if (st.types.length !== 3) bits.push(st.types.join('-'));
    if (st.status !== 'all') bits.push(st.status);
    if (st.section) bits.push(slug(st.section));
    if (st.society) bits.push(slug(st.society));
    return bits.join('_') + '_' + DATA.generated;
  }

  $('download-all-pdfs').addEventListener('click', e => {
    const { groups, st } = current;
    if (groups.length === 1) window.downloadPagePdf(groups[0].id);
    else if (groups.length) window.downloadAllPdfs(zipBase(st) + '.zip', e.currentTarget);
  });

  $('dl-csv').addEventListener('click', () => {
    const { list, st, groups } = current;
    const grouped = st.group !== 'none';
    const cols = [...(grouped ? [GROUP[st.group]] : []), 'Unit Name', 'SPO ID', 'Unit Type', 'University', 'Society', 'Section', 'Council',
      'Member Count', 'Members Required', 'Events (Reported)', 'Events Required', 'Chair', 'Counselor / Advisor',
      'Requirements Met', 'Overall Vitality', 'Missing'];
    const cell = v => { const s = String(v == null ? '' : v); return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const lines = [cols.map(cell).join(',')];
    (grouped ? groups.flatMap(g => g.ous.map(o => [g.title, o])) : list.map(o => [null, o])).forEach(([gt, o]) => {
      lines.push([...(grouped ? [gt] : []), o.n, o.id, TYPE_NAME[o.t], o.u, o.s, o.se, o.co, o.m, o.mm, o.e, o.em,
        o.ch ? 'Yes' : 'No', o.cn ? 'Yes' : 'No', `${o.rq}/3`, o.ok ? 'Met' : 'Not Met', o.miss.join('; ')].map(cell).join(','));
    });
    const blob = new Blob(['﻿' + lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = zipBase(st) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  $('print').addEventListener('click', () => window.print());
  $('pages').addEventListener('click', e => {
    const id = e.target && e.target.dataset && e.target.dataset.pdf;
    if (id) window.downloadPagePdf(id);
  });

  // ---------- presets: the common jobs, as starting points ----------
  const multiSection = ALL_SECTIONS.length > 1;
  const PRESETS = [
    { label: 'One report per Student Branch', who: 'SSACs: send each Student Branch its own report, with its Chapters and Affinity Groups',
      st: { group: 'branch' } },
    { label: multiSection ? 'Section reports by Student Branch' : 'Full report by Student Branch', who: 'Section Chairs and SSACs: every Student Branch with its Chapters and Affinity Groups',
      st: { group: multiSection ? 'section' : 'none', nest: true } },
    { label: multiSection ? 'Student Branches only, by Section' : 'Student Branches only', who: 'Region / Section SACs: the branches without their Chapters',
      st: { group: multiSection ? 'section' : 'none', types: ['branch'], nest: false } },
    { label: 'Chapters of one Society', who: 'Chapter chairs: then pick the Society in "Which OUs"',
      st: { group: 'society', types: ['chapter'], nest: false } },
    { label: 'OUs meeting vitality', who: 'Recognition: everyone with full vitality',
      st: { group: multiSection ? 'section' : 'none', status: 'met', nest: true } },
    { label: 'Quick wins: missing one requirement', who: 'Follow-up: OUs one step away, with what is missing',
      st: { group: multiSection ? 'section' : 'none', status: 'one', nest: true } },
  ];
  $('presets').innerHTML = PRESETS.map((p, i) => `<button type="button" class="preset" data-preset="${i}"><strong>${esc(p.label)}</strong><span>${esc(p.who)}</span></button>`).join('');
  $('presets').addEventListener('click', e => {
    const btn = e.target.closest('[data-preset]');
    if (!btn) return;
    const base = { council: '', section: '', university: '', society: '', q: '', types: Object.keys(TYPES), status: 'all', group: 'none', nest: true };
    // Keep the place the user narrowed to (council/section): presets change the "what" and "how".
    const keep = readControls();
    writeControls(Object.assign(base, { council: keep.council, section: keep.section }, PRESETS[btn.dataset.preset].st));
    update();
  });

  // ---------- wire up ----------
  if (ALL_COUNCILS.length < 2) { $('field-council').hidden = true; $('opt-group-council').hidden = true; }
  if (ALL_SECTIONS.length < 2) { $('field-section').hidden = true; $('opt-group-section').hidden = true; }

  const autoDownload = new URLSearchParams(location.search).get('download') === 'pdf';
  writeControls(stateFromUrl());
  update();

  let timer;
  document.querySelector('.controls').addEventListener('input', e => {
    clearTimeout(timer);
    timer = setTimeout(update, e.target.id === 'f-q' ? 250 : 0);
  });
  // ?download=pdf (from links / automations): export right away. Handled
  // here, not by report_export.js, because syncUrl() already dropped it.
  if (autoDownload) window.addEventListener('load', () => $('download-all-pdfs').click());
})();

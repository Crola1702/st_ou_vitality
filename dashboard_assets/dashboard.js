  const searchInput = document.getElementById('search');
  const universitySelect = document.getElementById('university-filter');
  const societySelect = document.getElementById('society-filter');
  // Only on multi-Section pages (the R9 whole-region dashboard).
  const councilSelect = document.getElementById('council-filter');
  const sectionSelect = document.getElementById('section-filter');
  const statusSelect = document.getElementById('status-filter');
  const typeBoxes = Array.from(document.querySelectorAll('#type-filter input'));
  const memberSlugByTable = { 'table-stb': 'stb', 'table-sbc': 'sbc', 'table-sba': 'sba' };
  const typeOfTable = { 'table-stb': 'branch', 'table-sbc': 'chapter', 'table-sba': 'ag' };
  const universityToSocieties = @@university_to_societies_json@@;
  const societyToUniversities = @@society_to_universities_json@@;

  function refineFilterOptions() {
    const uni = universitySelect.value;
    const soc = societySelect.value;

    const validSocieties = uni ? new Set(universityToSocieties[uni] || []) : null;
    Array.from(societySelect.options).forEach(opt => {
      if (!opt.value) return; // "All Societies"
      const visible = !validSocieties || validSocieties.has(opt.value);
      opt.hidden = !visible;
      opt.disabled = !visible;
    });
    if (soc && validSocieties && !validSocieties.has(soc)) societySelect.value = '';

    const validUniversities = soc ? new Set(societyToUniversities[soc] || []) : null;
    Array.from(universitySelect.options).forEach(opt => {
      if (!opt.value) return; // "All Universities"
      const visible = !validUniversities || validUniversities.has(opt.value);
      opt.hidden = !visible;
      opt.disabled = !visible;
    });
    if (uni && validUniversities && !validUniversities.has(uni)) universitySelect.value = '';

    // Council narrows the Section list.
    if (councilSelect && sectionSelect) {
      const council = councilSelect.value;
      Array.from(sectionSelect.options).forEach(opt => {
        if (!opt.value) return;
        const visible = !council || opt.dataset.council === council;
        opt.hidden = !visible;
        opt.disabled = !visible;
      });
      const chosen = sectionSelect.selectedOptions[0];
      if (chosen && chosen.value && chosen.disabled) sectionSelect.value = '';
    }
  }

  const selectedTypes = () => typeBoxes.filter(b => b.checked).map(b => b.value);

  // The single test for "is this OU in the current view": the tables, tiles
  // and "Export current view" all go through it.
  function rowMatches(row) {
    const q = searchInput.value.trim().toLowerCase();
    const req = parseInt(row.dataset.req, 10);
    const status = statusSelect.value;
    return (!q || row.dataset.name.includes(q) || row.dataset.spoid.includes(q))
      && (!universitySelect.value || row.dataset.university === universitySelect.value)
      && (!societySelect.value || row.dataset.society === societySelect.value)
      && (!councilSelect || !councilSelect.value || row.dataset.council === councilSelect.value)
      && (!sectionSelect || !sectionSelect.value || row.dataset.section === sectionSelect.value)
      && selectedTypes().includes(row.dataset.type)
      && (!status || (status === 'met' && req === 3) || (status === 'notmet' && req < 3)
          || (status === 'one' && req === 2) || (status === 'two' && req <= 1));
  }

  function applyFilters() {
    const sums = { stb: 0, sbc: 0, sba: 0 };
    const counts = { branch: [0, 0], chapter: [0, 0], ag: [0, 0] };  // [met, total]

    document.querySelectorAll('table').forEach(table => {
      const slug = memberSlugByTable[table.id];
      let shown = 0;
      table.querySelectorAll('.ou-row').forEach(row => {
        const match = rowMatches(row);
        row.style.display = match ? '' : 'none';
        if (match) {
          shown++;
          if (slug) sums[slug] += parseInt(row.dataset.members, 10) || 0;
          if (typeOfTable[table.id]) {
            counts[row.dataset.type][1]++;
            if (row.dataset.req === '3') counts[row.dataset.type][0]++;
          }
        }

        let next = row.nextElementSibling;
        while (next && next.classList.contains('detail-row')) {
          if (!match) next.style.display = 'none';
          next = next.nextElementSibling;
        }
      });
      const empty = table.querySelector('.filtered-empty');
      if (empty) empty.hidden = shown > 0 || !table.querySelector('.ou-row');
      if (table.id === 'table-quick-wins') {
        const badge = document.querySelector('.tab-btn[data-tab="quick-wins"] .tab-badge');
        if (badge) badge.textContent = shown;
      }
    });

    // A type that is switched off disappears with its section.
    document.querySelectorAll('.ou-section[data-type]').forEach(sec => {
      sec.hidden = !selectedTypes().includes(sec.dataset.type);
    });

    Object.keys(sums).forEach(slug => {
      const el = document.querySelector(`#members-${slug} .tile-value`);
      if (el) el.textContent = sums[slug];
    });

    const pct = (m, n) => (n ? Math.round((m / n) * 100) : 0);
    const met = counts.branch[0] + counts.chapter[0] + counts.ag[0];
    const total = counts.branch[1] + counts.chapter[1] + counts.ag[1];
    const setTile = (key, text) => { const el = document.querySelector(`.tile[data-tile="${key}"] .tile-value`); if (el) el.textContent = text; };
    setTile('total', String(total));
    setTile('met', `${met} (${pct(met, total)}%)`);
    Object.keys(counts).forEach(t => setTile(t, `${counts[t][0]}/${counts[t][1]} (${pct(counts[t][0], counts[t][1])}%)`));

    const groupTab = document.getElementById('tab-by-group');
    if (groupTab && !groupTab.hidden) renderGroupBars();

    updateURLParams();
  }

  function updateURLParams() {
    const params = new URLSearchParams();
    if (searchInput.value.trim()) params.set('q', searchInput.value.trim());
    if (councilSelect && councilSelect.value) params.set('council', councilSelect.value);
    if (sectionSelect && sectionSelect.value) params.set('section', sectionSelect.value);
    if (universitySelect.value) params.set('university', universitySelect.value);
    if (societySelect.value) params.set('society', societySelect.value);
    if (statusSelect.value) params.set('status', statusSelect.value);
    if (selectedTypes().length !== typeBoxes.length) params.set('types', selectedTypes().join(','));
    const qs = params.toString();
    history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);

    // "Open Section dashboard": the picked Section's own, lighter page, keeping the other filters.
    const sectionLink = document.getElementById('section-link');
    if (sectionLink) {
      const href = sectionSelect.value && sectionSelect.selectedOptions[0].dataset.href;
      sectionLink.hidden = !href;
      if (href) {
        params.delete('council');
        params.delete('section');
        sectionLink.href = href + (params.toString() ? `?${params}` : '');
      }
    }
  }

  function loadFiltersFromURL() {
    const params = new URLSearchParams(window.location.search);
    if (params.has('q')) searchInput.value = params.get('q');
    if (councilSelect && params.has('council')) councilSelect.value = params.get('council');
    if (sectionSelect && params.has('section')) sectionSelect.value = params.get('section');
    if (params.has('university')) universitySelect.value = params.get('university');
    if (params.has('society')) societySelect.value = params.get('society');
    if (params.has('status')) statusSelect.value = params.get('status');
    if (params.has('types')) {
      const want = params.get('types').split(',');
      if (typeBoxes.some(b => want.includes(b.value))) typeBoxes.forEach(b => { b.checked = want.includes(b.value); });
    }
  }

  searchInput.addEventListener('input', applyFilters);
  universitySelect.addEventListener('change', () => { refineFilterOptions(); applyFilters(); });
  societySelect.addEventListener('change', () => { refineFilterOptions(); applyFilters(); });
  [councilSelect, sectionSelect].forEach(sel => sel && sel.addEventListener('change', () => { refineFilterOptions(); applyFilters(); }));
  statusSelect.addEventListener('change', applyFilters);
  typeBoxes.forEach(b => b.addEventListener('change', () => {
    if (!typeBoxes.some(x => x.checked)) b.checked = true;  // keep at least one type
    applyFilters();
  }));

  loadFiltersFromURL();
  refineFilterOptions();
  applyFilters();

  function toggleRow(id) {
    const row = document.getElementById(id);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
  }

  // "By Group" tab: % of OUs at full vitality per value of one filter dimension.
  const optionLabels = sel => Object.fromEntries(Array.from(sel.options).map(o => [o.value, o.textContent]));
  const groupDims = [
    ...(councilSelect ? [{ id: 'council', label: 'Council', attr: 'council' }] : []),
    ...(sectionSelect ? [{ id: 'section', label: 'Section', attr: 'section' }] : []),
    { id: 'society', label: 'Society', attr: 'society', labels: optionLabels(societySelect) },
    { id: 'university', label: 'University', attr: 'university', labels: optionLabels(universitySelect) },
    { id: 'type', label: 'OU type', attr: 'type', labels: { branch: 'Student Branch', chapter: 'Chapter', ag: 'Affinity Group' } },
  ];
  const groupSelect = document.getElementById('group-by-select');
  groupSelect.innerHTML = groupDims.map(d => `<option value="${d.id}">${d.label}</option>`).join('');
  groupSelect.addEventListener('change', renderGroupBars);

  function renderGroupBars() {
    const dim = groupDims.find(d => d.id === groupSelect.value);
    const groups = {};
    document.querySelectorAll('#tab-overview .ou-row').forEach(row => {
      if (!rowMatches(row)) return;
      const key = row.dataset[dim.attr];
      if (!key) return;  // OUs without this attribute (e.g. no society) are left out
      const g = groups[key] || (groups[key] = [0, 0]);
      g[1]++;
      if (row.dataset.req === '3') g[0]++;
    });
    const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const rows = Object.entries(groups)
      .map(([key, [met, total]]) => ({ name: (dim.labels && dim.labels[key]) || key, met, total, pct: Math.round((met / total) * 100) }))
      .sort((a, b) => b.pct - a.pct || b.total - a.total);
    groupBarsView = { title: `Units at full vitality by ${dim.label}`, rows };
    document.getElementById('group-bars').innerHTML = rows.length
      ? rows.map(r => `<div class="group-bar-row"><span class="group-bar-name" title="${esc(r.name)}">${esc(r.name)}</span>`
          + `<span class="group-bar-track"><span class="group-bar-fill" style="width:${r.pct}%"></span></span>`
          + `<span class="group-bar-value">${r.pct}% (${r.met}/${r.total})</span></div>`).join('')
      : '<p class="req-note">No units match the current filters.</p>';
  }

  let groupBarsView = { title: '', rows: [] };

  // Always light-themed, like the other exports, whatever the dashboard theme.
  document.getElementById('group-bars-jpg').addEventListener('click', () => {
    const { title, rows } = groupBarsView;
    if (!rows.length) return;
    const W = 1000, rowH = 28, top = 56, nameW = 260, valueW = 130, pad = 20;
    const barX = pad + nameW, barW = W - barX - valueW - pad;
    const canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = top + rows.length * rowH + pad;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#1a1a1a';
    ctx.font = 'bold 18px sans-serif';
    ctx.fillText(title, pad, 26);
    ctx.font = '13px sans-serif';
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      let name = r.name;
      while (name.length > 1 && ctx.measureText(name).width > nameW - 10) name = name.slice(0, -1);
      ctx.fillStyle = '#1a1a1a';
      ctx.textAlign = 'left';
      ctx.fillText(name === r.name ? name : name + '…', pad, y + rowH / 2);
      ctx.fillStyle = '#e8e8e8';
      ctx.fillRect(barX, y + 5, barW, rowH - 10);
      ctx.fillStyle = '#2a78d6';
      ctx.fillRect(barX, y + 5, barW * r.pct / 100, rowH - 10);
      ctx.fillStyle = '#1a1a1a';
      ctx.textAlign = 'right';
      ctx.fillText(`${r.pct}% (${r.met}/${r.total})`, W - pad, y + rowH / 2);
    });
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/jpeg', 0.92);
    a.download = `vitality_${title.replace(/\W+/g, '_').toLowerCase()}.jpg`;
    a.click();
  });

  function showTab(name) {
    document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.id !== `tab-${name}`; });
    document.querySelectorAll('.tab-btn').forEach(b => { b.classList.toggle('active', b.dataset.tab === name); });
    if (name === 'by-group') renderGroupBars();
    if (name === 'trends') { renderTrendChart(); renderSocietyTrendChart(); renderGradeBarChart(); }
  }

  const trendData = @@trend_json@@;
  const trendSeriesDefs = @@trend_series_js@@;
  const societyTrendData = @@society_trend_json@@;
  const societyAllDefs = @@society_all_defs_js@@;
  const societyDefaultCodes = @@society_default_codes_js@@;
  const gradeTrendData = @@grade_trend_json@@;
  const gradeSeriesDefs = @@grade_series_js@@;
  const gradePromotionsByDate = @@grade_promotions_json@@;
  const SOCIETY_MAX_SELECTED = @@SOCIETY_TREND_MAX_SELECTED@@;
  const societySeriesVars = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6', '--series-7', '--series-8'];
  let societySelected = new Set(societyDefaultCodes);

  function renderLineChart(svgId, wrapId, tooltipId, dates, seriesDefs, dataSeries, mode) {
    const svg = document.getElementById(svgId);
    const wrap = document.getElementById(wrapId);
    const tooltip = document.getElementById(tooltipId);
    if (!svg || !wrap || !dates.length) return;

    const width = wrap.clientWidth || 700;
    const height = 280;
    const pad = { top: 16, right: 16, bottom: 28, left: mode === 'count' ? 48 : 40 };
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = '';

    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xFor = i => dates.length === 1 ? pad.left + plotW / 2 : pad.left + (i / (dates.length - 1)) * plotW;

    let yMax, yTicks, fmt;
    if (mode === 'percent') {
      yMax = 100;
      yTicks = [0, 25, 50, 75, 100];
      fmt = v => v + '%';
    } else {
      let maxVal = 0;
      seriesDefs.forEach(([key]) => {
        (dataSeries[key] || []).forEach(v => { if (v !== null && v !== undefined && v > maxVal) maxVal = v; });
      });
      const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000];
      let step = steps[steps.length - 1];
      for (const s of steps) { if (maxVal / s <= 4) { step = s; break; } }
      yMax = step * 4 || 4;
      yTicks = [0, step, step * 2, step * 3, step * 4];
      fmt = v => String(v);
    }
    const yFor = v => pad.top + plotH - (v / yMax) * plotH;

    const NS = 'http://www.w3.org/2000/svg';
    function el(tag, attrs) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      return e;
    }

    yTicks.forEach(v => {
      const y = yFor(v);
      svg.appendChild(el('line', { x1: pad.left, x2: width - pad.right, y1: y, y2: y, stroke: 'var(--gridline)', 'stroke-width': 1 }));
      const label = el('text', { x: pad.left - 8, y: y + 4, 'text-anchor': 'end', class: 'trend-axis-label' });
      label.textContent = fmt(v);
      svg.appendChild(label);
    });

    const labelIdxs = dates.length <= 6 ? dates.map((_, i) => i) : [0, Math.floor((dates.length - 1) / 2), dates.length - 1];
    labelIdxs.forEach(i => {
      const label = el('text', { x: xFor(i), y: height - 6, 'text-anchor': 'middle', class: 'trend-axis-label' });
      label.textContent = dates[i];
      svg.appendChild(label);
    });

    seriesDefs.forEach(([key, color]) => {
      const values = dataSeries[key] || [];
      const points = values.map((v, i) => v === null || v === undefined ? null : [xFor(i), yFor(v)]).filter(Boolean);
      if (points.length > 1) {
        const d = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ',' + p[1]).join(' ');
        svg.appendChild(el('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
      }
      points.forEach(([x, y]) => {
        svg.appendChild(el('circle', { cx: x, cy: y, r: 5, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 }));
      });
      if (points.length) {
        const [lx, ly] = points[points.length - 1];
        const lastVal = values[values.length - 1];
        const label = el('text', { x: Math.min(lx + 8, width - pad.right - 28), y: ly + 4, class: 'trend-direct-label' });
        label.textContent = fmt(lastVal);
        svg.appendChild(label);
      }
    });

    const crosshair = el('line', { x1: 0, x2: 0, y1: pad.top, y2: pad.top + plotH, stroke: 'var(--text-muted)', 'stroke-width': 1, visibility: 'hidden' });
    svg.appendChild(crosshair);

    svg.addEventListener('pointermove', (e) => {
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      let idx = 0, best = Infinity;
      dates.forEach((_, i) => {
        const d = Math.abs(xFor(i) - mx);
        if (d < best) { best = d; idx = i; }
      });
      crosshair.setAttribute('x1', xFor(idx));
      crosshair.setAttribute('x2', xFor(idx));
      crosshair.setAttribute('visibility', 'visible');

      tooltip.hidden = false;
      tooltip.style.left = Math.min(xFor(idx) + 12, width - 150) + 'px';
      tooltip.style.top = pad.top + 'px';
      tooltip.textContent = '';
      const dateEl = document.createElement('div');
      dateEl.className = 'trend-tooltip-date';
      dateEl.textContent = dates[idx];
      tooltip.appendChild(dateEl);
      seriesDefs.forEach(([key, color, label]) => {
        const v = (dataSeries[key] || [])[idx];
        const row = document.createElement('div');
        row.className = 'trend-tooltip-row';
        const keyEl = document.createElement('span');
        keyEl.className = 'trend-tooltip-key';
        keyEl.style.background = color;
        const valueEl = document.createElement('strong');
        valueEl.textContent = (v === null || v === undefined) ? '—' : fmt(v);
        const labelEl = document.createElement('span');
        labelEl.textContent = ' ' + label;
        row.appendChild(keyEl);
        row.appendChild(valueEl);
        row.appendChild(labelEl);
        tooltip.appendChild(row);
      });
    });
    svg.addEventListener('pointerleave', () => {
      crosshair.setAttribute('visibility', 'hidden');
      tooltip.hidden = true;
    });
  }

  function renderTrendChart() {
    renderLineChart('trend-svg', 'trend-svg-wrap', 'trend-tooltip', trendData.dates, trendSeriesDefs, trendData.series, 'percent');
  }

  let gradeBarPinnedIndex = null;

  function renderGradeBarChart() {
    const svg = document.getElementById('grade-bar-svg');
    const wrap = document.getElementById('grade-bar-svg-wrap');
    const tooltip = document.getElementById('grade-bar-tooltip');
    const detail = document.getElementById('grade-bar-detail');
    const dates = gradeTrendData.dates;
    if (!svg || !wrap || !dates.length) return;

    const width = wrap.clientWidth || 700;
    const height = 280;
    const pad = { top: 16, right: 16, bottom: 28, left: 48 };
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = '';

    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const groupW = plotW / dates.length;

    let maxVal = 0;
    gradeSeriesDefs.forEach(([key]) => {
      (gradeTrendData.series[key] || []).forEach(v => { if (v !== null && v !== undefined && v > maxVal) maxVal = v; });
    });
    const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000];
    let step = steps[steps.length - 1];
    for (const s of steps) { if (maxVal / s <= 4) { step = s; break; } }
    const yMax = step * 4 || 4;
    const yTicks = [0, step, step * 2, step * 3, step * 4];
    const yFor = v => pad.top + plotH - (v / yMax) * plotH;

    const NS = 'http://www.w3.org/2000/svg';
    function el(tag, attrs) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      return e;
    }
    function barPath(x, yTop, w, h) {
      const r = Math.max(0, Math.min(4, w / 2, h));
      return `M${x},${yTop + h} L${x},${yTop + r} Q${x},${yTop} ${x + r},${yTop} L${x + w - r},${yTop} Q${x + w},${yTop} ${x + w},${yTop + r} L${x + w},${yTop + h} Z`;
    }

    yTicks.forEach(v => {
      const y = yFor(v);
      svg.appendChild(el('line', { x1: pad.left, x2: width - pad.right, y1: y, y2: y, stroke: 'var(--gridline)', 'stroke-width': 1 }));
      const label = el('text', { x: pad.left - 8, y: y + 4, 'text-anchor': 'end', class: 'trend-axis-label' });
      label.textContent = String(v);
      svg.appendChild(label);
    });

    const BAR_MAX = 24, BAR_GAP = 2, GROUP_PAD = 0.18;
    const usableGroupW = groupW * (1 - GROUP_PAD * 2);
    const nSeries = gradeSeriesDefs.length;
    const barW = Math.max(4, Math.min(BAR_MAX, (usableGroupW - BAR_GAP * (nSeries - 1)) / nSeries));
    const groupContentW = barW * nSeries + BAR_GAP * (nSeries - 1);

    const groupRects = [];
    dates.forEach((date, i) => {
      const groupCenterX = pad.left + i * groupW + groupW / 2;
      const groupX = groupCenterX - groupContentW / 2;

      const dateLabel = el('text', { x: groupCenterX, y: height - 6, 'text-anchor': 'middle', class: 'trend-axis-label' });
      dateLabel.textContent = date;
      svg.appendChild(dateLabel);

      gradeSeriesDefs.forEach(([key, color], j) => {
        const v = (gradeTrendData.series[key] || [])[i];
        if (v === null || v === undefined) return;
        const isEstimated = !!(gradeTrendData.estimated && gradeTrendData.estimated[key] && gradeTrendData.estimated[key][i]);
        const x = groupX + j * (barW + BAR_GAP);
        const yTop = yFor(v);
        const h = pad.top + plotH - yTop;
        const barAttrs = { d: barPath(x, yTop, barW, h), fill: color };
        if (isEstimated) {
          barAttrs['fill-opacity'] = '0.45';
          barAttrs.stroke = color;
          barAttrs['stroke-width'] = '1.5';
          barAttrs['stroke-dasharray'] = '3,2';
        }
        svg.appendChild(el('path', barAttrs));
        const valueLabel = el('text', { x: x + barW / 2, y: yTop - 6, 'text-anchor': 'middle', class: 'trend-direct-label' });
        valueLabel.textContent = isEstimated ? `≈${v}` : String(v);
        svg.appendChild(valueLabel);
      });

      const hit = el('rect', {
        x: pad.left + i * groupW, y: pad.top, width: groupW, height: plotH, fill: 'transparent',
        cursor: 'pointer', tabindex: '0', role: 'button',
        'aria-label': `Show promotions recorded for ${date}`,
      });
      groupRects.push(hit);
      svg.appendChild(hit);
    });

    const highlight = el('rect', { x: 0, y: pad.top, width: groupW, height: plotH, fill: 'var(--text-muted)', opacity: 0.08, visibility: 'hidden' });
    svg.insertBefore(highlight, svg.firstChild);

    function showGroupTooltip(i) {
      const groupCenterX = pad.left + i * groupW + groupW / 2;
      highlight.setAttribute('x', pad.left + i * groupW);
      highlight.setAttribute('visibility', 'visible');

      tooltip.hidden = false;
      tooltip.style.left = Math.min(groupCenterX + 12, width - 170) + 'px';
      tooltip.style.top = pad.top + 'px';
      tooltip.textContent = '';
      const dateEl = document.createElement('div');
      dateEl.className = 'trend-tooltip-date';
      dateEl.textContent = dates[i];
      tooltip.appendChild(dateEl);
      gradeSeriesDefs.forEach(([key, color, label]) => {
        const v = (gradeTrendData.series[key] || [])[i];
        const row = document.createElement('div');
        row.className = 'trend-tooltip-row';
        const keyEl = document.createElement('span');
        keyEl.className = 'trend-tooltip-key';
        keyEl.style.background = color;
        const valueEl = document.createElement('strong');
        valueEl.textContent = (v === null || v === undefined) ? '—' : String(v);
        const labelEl = document.createElement('span');
        labelEl.textContent = ' ' + label;
        row.appendChild(keyEl);
        row.appendChild(valueEl);
        row.appendChild(labelEl);
        tooltip.appendChild(row);
      });
    }

    function showPromotionDetail(i) {
      if (!detail) return;
      detail.innerHTML = '';
      const heading = document.createElement('strong');
      if (i === 0) {
        heading.textContent = `${dates[i]}: no earlier snapshot to compare against.`;
        detail.appendChild(heading);
      } else {
        const entries = gradePromotionsByDate[dates[i]] || [];
        if (!entries.length) {
          heading.textContent = `No promotions recorded between ${dates[i - 1]} and ${dates[i]}.`;
          detail.appendChild(heading);
        } else {
          heading.textContent = `Promoted since ${dates[i - 1]}:`;
          detail.appendChild(heading);
          entries.forEach(({from: fromGrade, to: toGrade, count}) => {
            const row = document.createElement('div');
            row.className = 'promotion-row';
            row.textContent = `${count} ${fromGrade} → ${toGrade}`;
            detail.appendChild(row);
          });
        }
      }
      detail.hidden = false;
    }

    function highlightPinned() {
      if (gradeBarPinnedIndex === null) {
        highlight.setAttribute('visibility', 'hidden');
        return;
      }
      highlight.setAttribute('x', pad.left + gradeBarPinnedIndex * groupW);
      highlight.setAttribute('visibility', 'visible');
    }
    highlightPinned();
    if (gradeBarPinnedIndex !== null) showPromotionDetail(gradeBarPinnedIndex);

    groupRects.forEach((hit, i) => {
      hit.addEventListener('pointerenter', () => showGroupTooltip(i));
      hit.addEventListener('pointermove', () => showGroupTooltip(i));
      hit.addEventListener('pointerleave', () => {
        tooltip.hidden = true;
        highlightPinned();
      });
      function activate() {
        gradeBarPinnedIndex = (gradeBarPinnedIndex === i) ? null : i;
        highlightPinned();
        if (gradeBarPinnedIndex === null) {
          if (detail) detail.hidden = true;
        } else {
          showPromotionDetail(i);
        }
      }
      hit.addEventListener('click', activate);
      hit.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } });
    });
  }

  function currentSocietySeriesDefs() {
    return societyAllDefs
      .filter(([code]) => societySelected.has(code))
      .map(([code, label], i) => [code, `var(${societySeriesVars[i % societySeriesVars.length]})`, label]);
  }

  function toggleSocietyFilterPanel() {
    const panel = document.getElementById('society-filter-panel');
    if (panel) panel.hidden = !panel.hidden;
  }

  function renderSocietyFilterList() {
    const list = document.getElementById('society-filter-list');
    if (!list) return;
    list.innerHTML = '';
    societyAllDefs.forEach(([code, label]) => {
      const item = document.createElement('label');
      item.className = 'filter-check-item';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = societySelected.has(code);
      cb.disabled = !cb.checked && societySelected.size >= SOCIETY_MAX_SELECTED;
      cb.addEventListener('change', () => {
        if (cb.checked) societySelected.add(code); else societySelected.delete(code);
        onSocietySelectionChange();
      });
      const span = document.createElement('span');
      span.textContent = label;
      item.appendChild(cb);
      item.appendChild(span);
      list.appendChild(item);
    });
  }

  function renderSocietyLegend() {
    const legend = document.getElementById('society-trend-legend');
    if (!legend) return;
    legend.innerHTML = '';
    currentSocietySeriesDefs().forEach(([code, color, label]) => {
      const item = document.createElement('span');
      item.className = 'legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'legend-swatch';
      swatch.style.background = color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(label));
      legend.appendChild(item);
    });
  }

  function onSocietySelectionChange() {
    const toggle = document.getElementById('society-filter-toggle');
    if (toggle) toggle.textContent = `Filter societies (${societySelected.size} shown) ▾`;
    renderSocietyFilterList();
    renderSocietyLegend();
    renderSocietyTrendChart();
  }

  function resetSocietyFilter() {
    societySelected = new Set(societyDefaultCodes);
    onSocietySelectionChange();
  }

  function renderSocietyTrendChart() {
    renderLineChart('society-trend-svg', 'society-trend-svg-wrap', 'society-trend-tooltip', societyTrendData.dates, currentSocietySeriesDefs(), societyTrendData.series, 'count');
  }

  renderSocietyFilterList();
  renderSocietyLegend();

  window.addEventListener('resize', () => {
    const trendsTab = document.getElementById('tab-trends');
    if (trendsTab && !trendsTab.hidden) { renderTrendChart(); renderSocietyTrendChart(); renderGradeBarChart(); }
  });

  function sortByMembers(tableId, th) {
    const table = document.getElementById(tableId);
    const tbody = table.querySelector('tbody');
    const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
    table.querySelectorAll('th.sortable').forEach(h => { h.dataset.dir = ''; h.querySelector('.sort-arrow').textContent = ''; });
    th.dataset.dir = dir;
    th.querySelector('.sort-arrow').textContent = dir === 'asc' ? '▲' : '▼';

    const rows = Array.from(tbody.children);
    const groups = [];
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].classList.contains('ou-row')) {
        const group = [rows[i]];
        let j = i + 1;
        while (j < rows.length && rows[j].classList.contains('detail-row')) { group.push(rows[j]); j++; }
        groups.push({ group, members: parseInt(rows[i].dataset.members, 10) || 0 });
        i = j - 1;
      }
    }
    groups.sort((a, b) => dir === 'asc' ? a.members - b.members : b.members - a.members);
    // One DOM write: moving thousands of rows one by one froze the Region pages.
    const frag = document.createDocumentFragment();
    groups.forEach(g => frag.append(...g.group));
    tbody.prepend(frag);  // keeps the "no units match" row last
  }
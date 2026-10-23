  const CHART_DATA = @@CHART_DATA@@;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const tooltip = document.getElementById('tooltip');

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  }

  function niceMax(value) {
    if (value <= 5) return 5;
    const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    for (const step of [1, 2, 2.5, 5, 10]) {
      if (step * magnitude >= value) return step * magnitude;
    }
    return 10 * magnitude;
  }

  // Path for a bar with 4px rounded top corners and a square baseline.
  function barPath(x, y, w, h) {
    const r = Math.min(4, w / 2, h);
    return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} ` +
      `Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
  }

  function showTooltip(evt, text) {
    tooltip.textContent = text;
    tooltip.hidden = false;
    const pad = 12;
    let left = evt.clientX + pad;
    let top = evt.clientY + pad;
    const rect = tooltip.getBoundingClientRect();
    if (left + rect.width > window.innerWidth - 8) left = evt.clientX - rect.width - pad;
    if (top + rect.height > window.innerHeight - 8) top = evt.clientY - rect.height - pad;
    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
  }

  function hideTooltip() { tooltip.hidden = true; }

  // Single-series bar chart: one hue (--series-1), so no legend; the card title names it.
  function renderBarChart(containerId, data, unit, xLabelFn) {
    const container = document.getElementById(containerId);
    if (!data.length) {
      container.innerHTML = '<div class="empty">No attendances in the selected events.</div>';
      return;
    }
    const W = 560, H = 240, m = { top: 12, right: 8, bottom: 28, left: 36 };
    const plotW = W - m.left - m.right, plotH = H - m.top - m.bottom;
    const maxV = niceMax(Math.max(...data.map(d => d.value)));
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': container.previousElementSibling.textContent });
    const ticks = 5;  // niceMax() is always a multiple of 5, so count ticks stay whole numbers
    for (let i = 0; i <= ticks; i++) {
      const v = maxV * i / ticks;
      const y = m.top + plotH - plotH * i / ticks;
      svg.appendChild(svgEl('line', { class: 'gridline', x1: m.left, x2: W - m.right, y1: y, y2: y }));
      const label = svgEl('text', { class: 'axis-label', x: m.left - 6, y: y + 4, 'text-anchor': 'end' });
      label.textContent = Number.isInteger(v) ? v : v.toFixed(1);
      svg.appendChild(label);
    }
    const slot = plotW / data.length;
    const barW = Math.max(4, Math.min(48, slot - 2));  // >= 2px surface gap between bars
    const labelEvery = Math.ceil(data.length / 12);
    data.forEach((d, i) => {
      const x = m.left + i * slot + (slot - barW) / 2;
      const h = plotH * d.value / maxV;
      const y = m.top + plotH - h;
      const text = `${xLabelFn(d.label)}: ${d.value} ${d.value === 1 ? unit[0] : unit[1]}`;
      const hit = svgEl('rect', { class: 'bar-hit', x: m.left + i * slot, y: m.top, width: slot, height: plotH });
      const bar = svgEl('path', { class: 'bar', d: barPath(x, y, barW, h) });
      hit.addEventListener('mousemove', evt => { bar.classList.add('active'); showTooltip(evt, text); });
      hit.addEventListener('mouseleave', () => { bar.classList.remove('active'); hideTooltip(); });
      svg.appendChild(hit);
      svg.appendChild(bar);
      if (i % labelEvery === 0) {
        const label = svgEl('text', { class: 'axis-label', x: x + barW / 2, y: H - 10, 'text-anchor': 'middle' });
        label.textContent = d.label;
        svg.appendChild(label);
      }
    });
    container.appendChild(svg);
  }

  renderBarChart('chart-month', CHART_DATA.perMonth, ['attendance', 'attendances'], l => l);
  renderBarChart('chart-dist', CHART_DATA.distribution, ['person', 'people'],
    l => `${l} event${l === '1' ? '' : 's'}`);

  // Event rows expand their breakdowns.
  document.querySelectorAll('.event-row').forEach(row => {
    const toggle = () => {
      const detail = document.getElementById(row.dataset.target);
      detail.hidden = !detail.hidden;
      row.setAttribute('aria-expanded', String(!detail.hidden));
    };
    row.addEventListener('click', toggle);
    row.addEventListener('keydown', evt => {
      if (evt.key === 'Enter' || evt.key === ' ') { evt.preventDefault(); toggle(); }
    });
  });

  // Sortable tables: numeric when every non-empty cell parses as a number.
  document.querySelectorAll('table.sortable').forEach(tbl => {
    const headers = Array.from(tbl.tHead.rows[0].cells);
    headers.forEach((th, col) => {
      th.addEventListener('click', () => {
        const asc = th.getAttribute('aria-sort') !== 'ascending';
        headers.forEach(h => h.removeAttribute('aria-sort'));
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        const rows = Array.from(tbl.tBodies[0].rows);
        const value = r => r.cells[col].textContent.trim();
        const numeric = rows.every(r => value(r) === '' || !isNaN(parseFloat(value(r))));
        rows.sort((a, b) => {
          const va = value(a), vb = value(b);
          const cmp = numeric ? (parseFloat(va) || 0) - (parseFloat(vb) || 0) : va.localeCompare(vb);
          return asc ? cmp : -cmp;
        });
        rows.forEach(r => tbl.tBodies[0].appendChild(r));
      });
    });
  });

  // People text filter.
  const peopleFilter = document.getElementById('people-filter');
  peopleFilter.addEventListener('input', () => {
    const q = peopleFilter.value.trim().toLowerCase();
    for (const row of document.getElementById('people').tBodies[0].rows) {
      row.hidden = q !== '' && !row.textContent.toLowerCase().includes(q);
    }
  });

  // Theme toggle: an explicit choice beats the OS setting.
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
  });

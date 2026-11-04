// Batch PDF export for the grouped print reports (university, society,
// Student Branch, Section). Inlined into each report by
// generate_vitality_report.py; no library, no network.
//
// "Download all as PDF" turns every .group-page into its own PDF and packs
// them into one ZIP (folders from data-folder, names from data-filename),
// so each Student Branch / Section can be emailed its own file. The PDF
// writer is minimal on purpose: the base-14 Helvetica fonts (no embedding),
// WinAnsi text, and a layout engine that knows the handful of blocks these
// pages are made of (title, stats, bars, checklist, headings, notes,
// tables). Colors and bold come from the page's computed styles, so the PDF
// matches what is on screen. Opening a report with ?download=pdf starts the
// export immediately (the dashboard's "Reports & export" panel links there).

(function () {
  // ---------- fonts: Helvetica / Helvetica-Bold widths, chars 32..126 ----------
  const HELV = [278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584];
  const HELV_B = [278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,333,333,584,584,584,611,975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,944,667,667,611,333,278,333,584,556,333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,556,333,611,556,778,556,556,500,389,280,389,584];
  // Unicode -> WinAnsi bytes 0x80..0x9F (the rest of Latin-1 maps 1:1).
  const WINANSI = { 0x20AC: 0x80, 0x2026: 0x85, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97 };
  const SPECIAL_WIDTH = { 0x80: 556, 0x85: 1000, 0x91: 222, 0x92: 222, 0x93: 333, 0x94: 333, 0x95: 350, 0x96: 556, 0x97: 1000, 0xB7: 278, 0xA0: 278 };

  function toWinAnsi(str) {
    let out = '';
    for (const ch of str) {
      const c = ch.codePointAt(0);
      if ((c >= 32 && c < 127) || (c >= 0xA0 && c <= 0xFF)) out += ch;
      else if (WINANSI[c]) out += String.fromCharCode(WINANSI[c]);
      else if (c === 0x2192) out += '->';
      else if (c === 9 || c === 10 || c === 13) out += ' ';
      else {
        const base = ch.normalize('NFD').replace(/[̀-ͯ]/g, '');
        out += /^[\x20-\x7e]+$/.test(base) ? base : '?';
      }
    }
    return out;
  }

  function charWidth(code, bold) {
    if (code >= 32 && code <= 126) return (bold ? HELV_B : HELV)[code - 32];
    if (SPECIAL_WIDTH[code]) return SPECIAL_WIDTH[code];
    if (code >= 0xC0) {
      const base = String.fromCharCode(code).normalize('NFD').charCodeAt(0);
      if (base >= 32 && base <= 126) return (bold ? HELV_B : HELV)[base - 32];
    }
    return 556;
  }

  function textWidth(s, size, bold) {
    let w = 0;
    for (let i = 0; i < s.length; i++) w += charWidth(s.charCodeAt(i), bold);
    return (w / 1000) * size;
  }

  // ---------- colors ----------
  function parseColor(css, fallback) {
    const m = /rgba?\(([^)]+)\)/.exec(css || '');
    if (!m) return fallback || [0, 0, 0];
    const p = m[1].split(',').map(v => parseFloat(v));
    if (p.length === 4 && p[3] === 0) return fallback || [0, 0, 0];
    return [p[0] / 255, p[1] / 255, p[2] / 255];
  }
  const GREY = [0.4, 0.4, 0.4], DARK = [0.07, 0.07, 0.07], RULE = [0.88, 0.88, 0.87], BAND = [0.955, 0.955, 0.945];
  const f3 = n => (Math.round(n * 1000) / 1000).toString();
  const rgb = c => c.map(f3).join(' ');

  // ---------- text runs from the DOM ----------
  // A run is {text, bold, color}; text is already WinAnsi.
  function runsOf(el) {
    const runs = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || parent.closest('.no-print')) continue;
      let text = node.nodeValue.replace(/\s+/g, ' ');
      if (!text) continue;
      const cs = getComputedStyle(parent);
      if (cs.textTransform === 'uppercase') text = text.toUpperCase();
      const run = { text: toWinAnsi(text), bold: parseInt(cs.fontWeight, 10) >= 600, color: parseColor(cs.color, DARK) };
      const last = runs[runs.length - 1];
      if (last && last.bold === run.bold && last.color.join() === run.color.join()) last.text += run.text;
      else runs.push(run);
    }
    if (runs.length) {
      runs[0].text = runs[0].text.replace(/^ +/, '');
      runs[runs.length - 1].text = runs[runs.length - 1].text.replace(/ +$/, '');
    }
    return runs.filter(r => r.text);
  }

  function forceStyle(runs, opts) {
    return runs.map(r => ({ text: r.text, bold: opts.bold === undefined ? r.bold : opts.bold, color: opts.color || r.color }));
  }

  // Word-wrap runs into lines of segments {text, bold, color, w}.
  function wrap(runs, size, maxWidth) {
    const lines = [[]];
    let lineW = 0;
    const push = (seg) => { lines[lines.length - 1].push(seg); lineW += seg.w; };
    const newLine = () => { lines.push([]); lineW = 0; };
    for (const r of runs) {
      for (const tok of r.text.split(/( +)/)) {
        if (!tok) continue;
        const isSpace = /^ +$/.test(tok);
        let w = textWidth(tok, size, r.bold);
        if (isSpace) {
          if (lineW === 0) continue;
          push({ text: tok, bold: r.bold, color: r.color, w });
          continue;
        }
        if (lineW + w > maxWidth && lineW > 0) {
          const line = lines[lines.length - 1];
          while (line.length && /^ +$/.test(line[line.length - 1].text)) line.pop();
          newLine();
        }
        if (w > maxWidth) {
          // A single word wider than the column: break it by characters.
          let chunk = '';
          for (const ch of tok) {
            const cw = textWidth(chunk + ch, size, r.bold);
            if (cw > maxWidth - lineW && chunk) {
              push({ text: chunk, bold: r.bold, color: r.color, w: textWidth(chunk, size, r.bold) });
              newLine();
              chunk = ch;
            } else chunk += ch;
          }
          w = textWidth(chunk, size, r.bold);
          push({ text: chunk, bold: r.bold, color: r.color, w });
        } else push({ text: tok, bold: r.bold, color: r.color, w });
      }
    }
    for (const line of lines) while (line.length && /^ +$/.test(line[line.length - 1].text)) line.pop();
    return lines.filter((l, i) => l.length || i === 0);
  }

  const lineWidth = line => line.reduce((s, seg) => s + seg.w, 0);

  // ---------- PDF document ----------
  const PAGE_W = 612, PAGE_H = 792, MARGIN = 40, FOOTER = 22;
  const CONTENT_W = PAGE_W - 2 * MARGIN;

  function esc(s) { return s.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)'); }

  class Doc {
    constructor(title) { this.title = toWinAnsi(title); this.pages = []; this.newPage(); }
    newPage() { this.ops = []; this.pages.push(this.ops); this.y = MARGIN; }
    room(h) { return this.y + h <= PAGE_H - MARGIN - FOOTER; }
    // Start a new page unless `h` points still fit (and we're not at the top).
    ensure(h) { if (!this.room(h) && this.y > MARGIN) { this.newPage(); return true; } return false; }
    text(x, baseline, s, size, bold, color) {
      if (!s) return;
      this.ops.push(`BT /${bold ? 'F2' : 'F1'} ${f3(size)} Tf ${rgb(color)} rg ${f3(x)} ${f3(PAGE_H - baseline)} Td (${esc(s)}) Tj ET`);
    }
    line(segs, x, baseline, size) {
      let cx = x;
      for (const s of segs) { this.text(cx, baseline, s.text, size, s.bold, s.color); cx += s.w; }
    }
    rect(x, y, w, h, color) { this.ops.push(`${rgb(color)} rg ${f3(x)} ${f3(PAGE_H - y - h)} ${f3(w)} ${f3(h)} re f`); }
    stroke(x, y, w, h, color) { this.ops.push(`0.6 w ${rgb(color)} RG ${f3(x)} ${f3(PAGE_H - y - h)} ${f3(w)} ${f3(h)} re S`); }
    hline(x1, x2, y, color) { this.ops.push(`0.5 w ${rgb(color)} RG ${f3(x1)} ${f3(PAGE_H - y)} m ${f3(x2)} ${f3(PAGE_H - y)} l S`); }

    // Wrapped paragraph at the cursor.
    para(runs, size, opts = {}) {
      const lh = size * 1.25;
      const lines = wrap(runs, size, opts.width || CONTENT_W);
      for (const l of lines) {
        this.ensure(lh);
        this.line(l, opts.x || MARGIN, this.y + size, size);
        this.y += lh;
      }
      this.y += opts.after || 0;
    }

    bytes() {
      const n = this.pages.length;
      const footerTitle = this.title;
      this.pages.forEach((ops, i) => {
        const label = `${footerTitle}  ·  ${i + 1}/${n}`;
        ops.push(`BT /F1 7 Tf ${rgb(GREY)} rg ${MARGIN} ${MARGIN - 18} Td (${esc(toWinAnsi(label))}) Tj ET`);
      });
      const objs = [];
      objs[1] = '<< /Type /Catalog /Pages 2 0 R >>';
      const kids = this.pages.map((_, i) => `${6 + i * 2} 0 R`).join(' ');
      objs[2] = `<< /Type /Pages /Kids [${kids}] /Count ${n} >>`;
      objs[3] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>';
      objs[4] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>';
      objs[5] = `<< /Title (${esc(this.title)}) /Producer (IEEE Student OU Vitality) >>`;
      this.pages.forEach((ops, i) => {
        const content = ops.join('\n');
        objs[6 + i * 2] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${7 + i * 2} 0 R >>`;
        objs[7 + i * 2] = `<< /Length ${content.length} >>\nstream\n${content}\nendstream`;
      });
      let out = '%PDF-1.4\n%âãÏÓ\n';
      const offsets = [];
      for (let i = 1; i < objs.length; i++) {
        offsets[i] = out.length;
        out += `${i} 0 obj\n${objs[i]}\nendobj\n`;
      }
      const xref = out.length;
      out += `xref\n0 ${objs.length}\n0000000000 65535 f \n`;
      for (let i = 1; i < objs.length; i++) out += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
      out += `trailer\n<< /Size ${objs.length} /Root 1 0 R /Info 5 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
      const bytes = new Uint8Array(out.length);
      for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xFF;
      return bytes;
    }
  }

  // ---------- blocks ----------
  function drawStats(doc, el) {
    const stats = [...el.querySelectorAll('.stat')];
    const colW = Math.min(170, CONTENT_W / Math.max(stats.length, 1));
    doc.ensure(34);
    stats.forEach((s, i) => {
      const x = MARGIN + i * colW;
      const label = s.querySelector('.stat-label'), value = s.querySelector('.stat-value');
      if (label) doc.line(wrap(forceStyle(runsOf(label), { color: GREY }), 6.5, colW - 8)[0], x, doc.y + 7, 6.5);
      if (value) doc.line(wrap(forceStyle(runsOf(value), { bold: true }), 14, colW - 8)[0], x, doc.y + 24, 14);
    });
    doc.y += 34;
  }

  function drawBars(doc, el) {
    const rows = [...el.querySelectorAll('.bar-row')];
    doc.ensure(rows.length * 13 + 6);
    const labelW = 80, valueW = 26, trackX = MARGIN + labelW, trackW = CONTENT_W - labelW - valueW;
    for (const row of rows) {
      const label = row.querySelector('.bar-label'), fill = row.querySelector('.bar-fill'), value = row.querySelector('.bar-value');
      if (label) doc.line(wrap(runsOf(label), 7.5, labelW - 6)[0], MARGIN, doc.y + 8, 7.5);
      doc.rect(trackX, doc.y + 2, trackW, 7, BAND);
      if (fill) {
        const pct = parseFloat(fill.style.width) || 0;
        doc.rect(trackX, doc.y + 2, (trackW * pct) / 100, 7, parseColor(getComputedStyle(fill).backgroundColor, GREY));
      }
      if (value) {
        const segs = wrap(forceStyle(runsOf(value), { bold: true }), 7.5, valueW)[0];
        doc.line(segs, MARGIN + CONTENT_W - lineWidth(segs), doc.y + 8, 7.5);
      }
      doc.y += 13;
    }
    doc.y += 8;
  }

  function drawChecklist(doc, el) {
    const boxes = [...el.querySelectorAll('.check')];
    const perRow = Math.max(1, Math.min(boxes.length, Math.floor(CONTENT_W / 95)));
    const gap = 6, boxW = (CONTENT_W - gap * (perRow - 1)) / perRow;
    for (let i = 0; i < boxes.length; i += perRow) {
      const row = boxes.slice(i, i + perRow).map(b => {
        const label = wrap(forceStyle(runsOf(b.querySelector('.check-label') || b), { color: GREY }), 6.5, boxW - 12);
        const value = wrap(forceStyle(runsOf(b.querySelector('.check-value') || b), { bold: true }), 10.5, boxW - 12);
        return { label, value, h: 10 + label.length * 8.5 + value.length * 13 };
      });
      const h = Math.max(...row.map(b => b.h));
      doc.ensure(h + gap);
      row.forEach((b, j) => {
        const x = MARGIN + j * (boxW + gap);
        doc.stroke(x, doc.y, boxW, h, RULE);
        let y = doc.y + 4;
        for (const l of b.label) { doc.line(l, x + 6, y + 6.5, 6.5); y += 8.5; }
        y += 1;
        for (const l of b.value) { doc.line(l, x + 6, y + 10.5, 10.5); y += 13; }
      });
      doc.y += h + gap;
    }
    doc.y += 2;
  }

  function drawTable(doc, table) {
    const SIZE = 7.5, LH = 9.5, PAD = 3, HEAD = 6.5;
    const headCells = [...table.querySelectorAll('thead th')];
    const head = headCells.map(th => ({
      runs: forceStyle(runsOf(th), { bold: true, color: GREY }),
      right: th.classList.contains('num'),
    }));
    const ncol = Math.max(head.length, 1);
    const rows = [...table.querySelectorAll('tbody tr')].filter(tr => !tr.hidden && getComputedStyle(tr).display !== 'none').map(tr => {
      const cells = [...tr.children];
      if (cells.length === 1 && (cells[0].colSpan || 1) > 1) return { band: forceStyle(runsOf(cells[0]), { bold: true }) };
      return {
        child: tr.classList.contains('child'),
        cells: cells.map(td => ({ runs: runsOf(td), right: td.classList.contains('num') })),
      };
    });

    // Column widths: natural (one-line) width, but never below the longest
    // word; squeeze the wrap-friendly columns first when it doesn't fit.
    const nat = new Array(ncol).fill(20), minw = new Array(ncol).fill(18);
    const consider = (i, runs, size) => {
      if (i >= ncol) return;
      const text = runs.map(r => r.text).join('');
      const bold = runs.some(r => r.bold);
      nat[i] = Math.max(nat[i], Math.min(textWidth(text, size, bold) + 2 * PAD, 260));
      for (const word of text.split(' ')) minw[i] = Math.max(minw[i], Math.min(textWidth(word, size, bold) + 2 * PAD, 110));
    };
    head.forEach((h, i) => consider(i, h.runs, HEAD));
    rows.forEach(r => r.cells && r.cells.forEach((c, i) => consider(i, c.runs, SIZE)));
    let widths;
    const sumNat = nat.reduce((a, b) => a + b, 0), sumMin = minw.reduce((a, b) => a + b, 0);
    if (sumNat <= CONTENT_W) widths = nat.map(w => w + (CONTENT_W - sumNat) * (w / sumNat));
    else if (sumMin >= CONTENT_W) widths = minw.map(w => (w * CONTENT_W) / sumMin);
    else {
      const slack = CONTENT_W - sumMin, want = nat.map((w, i) => w - minw[i]), sumWant = want.reduce((a, b) => a + b, 0) || 1;
      widths = minw.map((w, i) => w + (slack * want[i]) / sumWant);
    }
    const xs = widths.reduce((acc, w, i) => (acc.push(i ? acc[i - 1] + widths[i - 1] : MARGIN), acc), []);

    const drawHead = () => {
      if (!head.length) return;
      const lines = head.map((h, i) => wrap(h.runs, HEAD, widths[i] - 2 * PAD));
      const h = Math.max(...lines.map(l => l.length)) * 8 + 5;
      lines.forEach((ls, i) => ls.forEach((l, k) => {
        const x = head[i].right ? xs[i] + widths[i] - PAD - lineWidth(l) : xs[i] + PAD;
        doc.line(l, x, doc.y + 7 + k * 8, HEAD);
      }));
      doc.y += h;
      doc.hline(MARGIN, MARGIN + CONTENT_W, doc.y, RULE);
    };

    doc.ensure(40);
    drawHead();
    for (const r of rows) {
      if (r.band) {
        const lines = wrap(r.band, 8, CONTENT_W - 2 * PAD);
        const h = lines.length * 10 + 6;
        if (doc.ensure(h + 2 * (LH + 5))) drawHead();  // keep a family header with its first rows
        doc.rect(MARGIN, doc.y, CONTENT_W, h, BAND);
        lines.forEach((l, k) => doc.line(l, MARGIN + PAD, doc.y + 10 + k * 10, 8));
        doc.y += h;
        continue;
      }
      const cellLines = r.cells.slice(0, ncol).map((c, i) => wrap(c.runs, SIZE, widths[i] - 2 * PAD - (i === 0 && r.child ? 10 : 0)));
      const h = Math.max(1, ...cellLines.map(l => l.length)) * LH + 5;
      if (doc.ensure(h)) drawHead();
      cellLines.forEach((ls, i) => ls.forEach((l, k) => {
        const indent = i === 0 && r.child ? 10 : 0;
        const x = r.cells[i].right ? xs[i] + widths[i] - PAD - lineWidth(l) : xs[i] + PAD + indent;
        doc.line(l, x, doc.y + 3 + SIZE + k * LH, SIZE);
      }));
      doc.y += h;
      doc.hline(MARGIN, MARGIN + CONTENT_W, doc.y, RULE);
    }
    doc.y += 10;
  }

  function renderGroupPage(section) {
    const title = (section.querySelector('h1') || section).textContent.trim();
    const doc = new Doc(title);
    for (const el of section.children) {
      if (el.classList.contains('no-print') || el.classList.contains('page-toolbar')) continue;
      if (el.tagName === 'H1') doc.para(forceStyle(runsOf(el), { bold: true, color: DARK }), 18, { after: 2 });
      else if (el.tagName === 'H2') { doc.y += 6; doc.ensure(60); doc.para(runsOf(el).map(r => ({ ...r, bold: r.bold })), 11, { after: 4 }); }
      else if (el.classList.contains('context')) doc.para(runsOf(el), 10, { after: 1 });
      else if (el.classList.contains('subtitle')) doc.para(forceStyle(runsOf(el), { color: GREY }), 8, { after: 10 });
      else if (el.classList.contains('stat-row')) drawStats(doc, el);
      else if (el.classList.contains('bar-chart')) drawBars(doc, el);
      else if (el.classList.contains('checklist')) drawChecklist(doc, el);
      else if (el.tagName === 'TABLE') drawTable(doc, el);
      else { const runs = runsOf(el); if (runs.length) doc.para(runs, 9, { after: 6 }); }
    }
    return doc.bytes();
  }

  // ---------- ZIP (stored; PDFs here are small) ----------
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function makeZip(files) {
    const enc = new TextEncoder();
    const chunks = [], central = [];
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    let offset = 0;
    for (const f of files) {
      const name = enc.encode(f.name), data = f.data, crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);  // UTF-8 file names
      local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true); local.setUint32(18, data.length, true);
      local.setUint32(22, data.length, true); local.setUint16(26, name.length, true);
      chunks.push(local, name, data);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true);
      cen.setUint16(8, 0x0800, true); cen.setUint16(12, dosTime, true); cen.setUint16(14, dosDate, true);
      cen.setUint32(16, crc, true);
      cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
      cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
      central.push(cen, name);
      offset += 30 + name.length + data.length;
    }
    const cenSize = central.reduce((s, c) => s + c.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true);
    end.setUint16(10, files.length, true); end.setUint32(12, cenSize, true); end.setUint32(16, offset, true);
    return new Blob([...chunks, ...central, end], { type: 'application/zip' });
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  const pdfName = page => (page.dataset.filename || page.id) + '.pdf';

  // ---------- public entry points ----------
  window.downloadPagePdf = function (id) {
    const page = document.getElementById(id);
    if (page) saveBlob(new Blob([renderGroupPage(page)], { type: 'application/pdf' }), pdfName(page));
  };

  window.downloadAllPdfs = async function (zipName, button) {
    const pages = [...document.querySelectorAll('.group-page')];
    const label = button ? button.textContent : '';
    if (button) button.disabled = true;
    try {
      const files = [];
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        files.push({ name: (page.dataset.folder ? page.dataset.folder + '/' : '') + pdfName(page), data: renderGroupPage(page) });
        if (button && i % 5 === 0) {
          button.textContent = `Building PDFs ${i + 1}/${pages.length}…`;
          await new Promise(r => setTimeout(r));  // let the label repaint
        }
      }
      saveBlob(makeZip(files), zipName);
    } finally {
      if (button) { button.textContent = label; button.disabled = false; }
    }
  };

  // Exposed for tests / debugging.
  window.__reportExport = { renderGroupPage, makeZip, toWinAnsi, wrap };

  window.addEventListener('load', () => {
    if (new URLSearchParams(location.search).get('download') === 'pdf') {
      const button = document.getElementById('download-all-pdfs');
      if (button) button.click();
    }
  });
})();

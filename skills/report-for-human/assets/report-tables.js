/* Optional local column sizing. Native range inputs supply pointer + keyboard UI. */
(function () {
  'use strict';
  var MIN = 120, MAX = 960;
  function init() {
    document.querySelectorAll('.rfh-table[data-rfh-resizable]').forEach(function (table) {
      if (table.hasAttribute('data-rfh-table-ready')) return;
      var wrap = table.parentElement;
      var head = table.tHead;
      if (!wrap || !wrap.classList.contains('rfh-table-wrap') || !head || head.rows.length !== 1) return;
      var headers = Array.from(head.rows[0].cells);
      // Spanned, nested, and very wide tables need author-designed reading behavior.
      if (headers.length < 2 || headers.length > 8 || headers.some(function (cell) { return cell.tagName !== 'TH'; }) ||
          table.querySelector('table') || Array.from(table.rows).some(function (row) {
            return row.cells.length !== headers.length || Array.from(row.cells).some(function (cell) {
              return cell.colSpan !== 1 || cell.rowSpan !== 1;
            });
          })) return;
      var groups = Array.from(table.children).filter(function (el) { return el.tagName === 'COLGROUP'; });
      if (groups.length !== 1 || groups[0].children.length !== headers.length ||
          Array.from(groups[0].children).some(function (col) { return col.tagName !== 'COL' || col.span !== 1; })) return;
      var cols = Array.from(groups[0].children);
      var original = cols.map(function (col) { return col.style.width; });
      var originalWidth = table.style.width, originalMin = table.style.minWidth;
      var manual = false, widths = [], inputs = [], outputs = [];
      var panel = document.createElement('details'); panel.className = 'rfh-table-tools';
      var summary = document.createElement('summary'); summary.textContent = '调整列宽'; panel.appendChild(summary);
      var tip = document.createElement('p');
      tip.textContent = '拖动滑块，或聚焦后用方向键微调、Home / End 调到边界。超出可见宽度时横向滚动。仅本页生效，打印恢复自适应。';
      panel.appendChild(tip);
      var sliders = document.createElement('div'); sliders.className = 'rfh-table-sliders'; panel.appendChild(sliders);
      var reset = document.createElement('button'); reset.type = 'button'; reset.textContent = '恢复默认列宽'; reset.disabled = true;
      function sync() {
        if (!manual) {
          var measured = headers.map(function (cell) { return Math.round(cell.getBoundingClientRect().width); });
          if (measured.some(function (w) { return w <= 0; })) return false;
          widths = measured;
        }
        widths.forEach(function (width, i) {
          // Bounds include unusually wide/narrow authored defaults without moving them on open.
          if (!manual) { inputs[i].min = Math.min(MIN, width); inputs[i].max = Math.max(MAX, width); }
          inputs[i].value = width; outputs[i].value = width + ' px';
          inputs[i].setAttribute('aria-valuetext', width + ' 像素');
        });
        return true;
      }
      headers.forEach(function (header, i) {
        var label = document.createElement('label');
        var name = document.createElement('span'); name.textContent = header.textContent.trim() || '第 ' + (i + 1) + ' 列';
        var output = document.createElement('output'); output.setAttribute('aria-hidden', 'true');
        var input = document.createElement('input'); input.type = 'range'; input.step = '1';
        input.setAttribute('aria-label', name.textContent + ' 列宽');
        label.appendChild(name); label.appendChild(output); label.appendChild(input); sliders.appendChild(label);
        inputs.push(input); outputs.push(output);
        input.addEventListener('input', function () {
          var requested = Number(input.value);
          if (!Number.isFinite(requested) || (!manual && !sync())) return;
          widths[i] = Math.max(Number(input.min), Math.min(Number(input.max), requested));
          manual = true;
          cols.forEach(function (col, n) { col.style.width = widths[n] + 'px'; });
          table.style.minWidth = '0px'; table.style.width = widths.reduce(function (sum, w) { return sum + w; }, 0) + 'px';
          reset.disabled = false; sync();
        });
      });
      reset.addEventListener('click', function () {
        manual = false;
        cols.forEach(function (col, i) { col.style.width = original[i]; });
        table.style.width = originalWidth; table.style.minWidth = originalMin;
        reset.disabled = true; sync();
      });
      panel.appendChild(reset);
      panel.addEventListener('toggle', function () { if (panel.open) sync(); });
      window.addEventListener('resize', function () { if (panel.open && !manual) sync(); });
      wrap.parentNode.insertBefore(panel, wrap);
      table.setAttribute('data-rfh-table-ready', '');
      // Measurement is deferred to opening the controls, including tables inside closed evidence.
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

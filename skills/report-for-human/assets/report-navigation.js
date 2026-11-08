/* Offline progressive enhancement: required reference tabs and image inspection. */
(() => {
  'use strict';
  function init() {
    document.querySelectorAll('.rfh-tabs').forEach(group => {
      if (group.hasAttribute('data-tabs-ready')) return;
      const list = [...group.children].find(el => el.getAttribute('role') === 'tablist');
      if (!list) return;
      const tabs = [...list.children];
      const panels = tabs.map(tab => document.getElementById(tab.getAttribute('aria-controls')));
      if (!tabs.length || tabs.some(tab => tab.tagName !== 'BUTTON' || !tab.id) ||
          panels.some(panel => !panel || panel.parentElement !== group || panel.getAttribute('role') !== 'tabpanel') ||
          new Set(panels).size !== tabs.length) return;
      function select(index, focus = false) {
        tabs.forEach((tab, i) => {
          tab.setAttribute('role', 'tab');
          tab.setAttribute('aria-selected', String(i === index));
          tab.tabIndex = i === index ? 0 : -1;
          panels[i].hidden = i !== index;
          panels[i].setAttribute('aria-labelledby', tab.id);
          panels[i].tabIndex = 0;
        });
        if (focus) tabs[index].focus();
      }
      tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => select(index));
        tab.addEventListener('keydown', event => {
          let next;
          if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
          if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
          if (event.key === 'Home') next = 0;
          if (event.key === 'End') next = tabs.length - 1;
          if (next === undefined) return;
          event.preventDefault(); select(next, true);
        });
      });
      select(Math.max(0, tabs.findIndex(tab => tab.getAttribute('aria-selected') === 'true')));
      group.setAttribute('data-tabs-ready', '');
    });

    const links = [...document.querySelectorAll('.rfh-image-link')];
    if (!links.length || typeof HTMLDialogElement === 'undefined' || !HTMLDialogElement.prototype.showModal) return;
    const dialog = document.createElement('dialog');
    dialog.className = 'rfh-image-dialog';
    dialog.setAttribute('aria-label', '放大图片');
    const toolbar = document.createElement('div'); toolbar.className = 'rfh-image-toolbar';
    const title = document.createElement('strong'); title.textContent = '放大图片';
    const zoom = document.createElement('button'); zoom.type = 'button'; zoom.textContent = '查看原始尺寸'; zoom.setAttribute('aria-pressed', 'false');
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '关闭';
    const stage = document.createElement('div'); stage.className = 'rfh-image-stage'; stage.tabIndex = 0; stage.setAttribute('aria-label', '图片查看区，原始尺寸时可滚动');
    const img = document.createElement('img');
    const caption = document.createElement('p'); caption.className = 'rfh-image-caption';
    toolbar.append(title, zoom, close); stage.append(img); dialog.append(toolbar, stage, caption);
    (document.querySelector('.human-report') || document.body).append(dialog);
    let opener = null;
    zoom.addEventListener('click', () => {
      const original = dialog.dataset.original !== 'true';
      dialog.dataset.original = String(original);
      zoom.setAttribute('aria-pressed', String(original));
      zoom.textContent = original ? '适合窗口' : '查看原始尺寸';
    });
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      const box = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
    });
    dialog.addEventListener('close', () => {
      img.removeAttribute('src');
      if (opener && opener.isConnected) opener.focus();
      opener = null;
    });
    links.forEach(link => {
      const preview = link.querySelector('img');
      // The report is self-contained. Never turn an arbitrary link into a network request.
      const source = link.getAttribute('href') || '';
      if (!preview || !/^data:image\/(?:png|jpe?g|webp|gif|avif);base64,/i.test(source)) return;
      link.setAttribute('aria-haspopup', 'dialog');
      link.addEventListener('click', event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0) return;
        img.src = source; img.alt = preview.alt;
        caption.textContent = link.closest('figure')?.querySelector('figcaption')?.textContent || preview.alt;
        dialog.dataset.original = 'false'; zoom.setAttribute('aria-pressed', 'false'); zoom.textContent = '查看原始尺寸';
        opener = link;
        try { dialog.showModal(); } catch (_) { opener = null; return; }
        event.preventDefault(); close.focus(); stage.scrollTop = 0; stage.scrollLeft = 0;
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();

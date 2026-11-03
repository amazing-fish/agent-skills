/* Local revision, 2026-11-03: copy the recorded source path, never a preview URL. */
(() => {
  'use strict';
  const root = document.documentElement;
  const key = 'report-for-human:theme';
  let initial = 'light';
  try {
    const saved = localStorage.getItem(key);
    if (saved === 'light' || saved === 'dark') initial = saved;
  } catch { /* Reading remains available when storage is blocked. */ }
  root.dataset.reportTheme = initial;

  function locationToCopy() {
    const path = document.querySelector('meta[name="report-source-path"]')?.content?.trim();
    if (!path || !(/^[a-z]:[\\/]/i.test(path) || /^\\\\[^\\]+\\[^\\]+/.test(path) || path.startsWith('/'))) return null;
    return path;
  }

  function ready() {
    const toggle = document.querySelector('[data-rfh-theme-toggle]');
    const copy = document.querySelector('[data-rfh-copy-path]');
    const status = document.querySelector('[data-rfh-status]');
    const manual = document.querySelector('[data-rfh-manual]');
    const pathField = document.querySelector('[data-rfh-manual-path]');
    if (!toggle || !copy || !status || !manual || !pathField) return;
    function showTheme() {
      const dark = root.dataset.reportTheme === 'dark';
      toggle.textContent = dark ? '切换浅色' : '切换深色';
      toggle.setAttribute('aria-pressed', String(dark));
      toggle.title = dark ? '当前为深色，切换为浅色' : '当前为浅色，切换为深色';
    }
    toggle.disabled = false;
    copy.disabled = false;
    showTheme();
    toggle.addEventListener('click', () => {
      root.dataset.reportTheme = root.dataset.reportTheme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, root.dataset.reportTheme); } catch { /* The current page still switches. */ }
      showTheme();
    });
    copy.addEventListener('click', async () => {
      const path = locationToCopy();
      status.textContent = '';
      manual.hidden = true;
      if (!path) {
        status.textContent = '报告尚未记录本机文件位置，请用生成器重新生成。';
        return;
      }
      copy.disabled = true;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(path);
        status.textContent = '已复制文件位置';
      } catch {
        manual.hidden = false;
        pathField.value = path;
        pathField.focus();
        pathField.select();
        status.textContent = '浏览器未允许自动复制，已选中位置，可手动复制。';
      } finally { copy.disabled = false; }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once:true});
  else ready();
})();

(function () {
  'use strict';
  document.addEventListener('click', async function (event) {
    var button = event.target.closest('[data-copy-target]');
    if (!button) return;
    var id = button.getAttribute('data-copy-target');
    var target = document.getElementById(id);
    var status = Array.from(document.querySelectorAll('[data-copy-status]')).find(function (el) {
      return el.getAttribute('data-copy-status') === id;
    });
    function report(value) { if (status) status.textContent = value; }
    if (!target || !target.textContent.trim()) { report('正文缺失，未复制'); return; }
    var text = target.textContent;
    var copied = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        copied = true;
      }
    } catch (ignore) {}
    if (!copied) {
      var input = document.createElement('textarea');
      input.value = text;
      input.style.position = 'fixed';
      input.style.opacity = '0';
      document.body.appendChild(input);
      try {
        input.focus(); input.select();
        copied = !!document.execCommand('copy');
      } catch (ignore) {}
      finally { input.remove(); button.focus(); }
    }
    if (copied) { report('已复制本段提示词'); return; }
    var selected = false;
    try {
      var range = document.createRange();
      range.selectNodeContents(target);
      var selection = window.getSelection();
      if (selection) { selection.removeAllRanges(); selection.addRange(range); selected = true; }
    } catch (ignore) {}
    report(selected ? '自动复制未成功，正文已选中，请手动复制' : '自动复制未成功，请选中正文后手动复制');
  });
})();

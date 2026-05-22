function toggleNav(){
  const el = document.getElementById('mainnav');
  el.classList.toggle('show');
}
function confirmSubmit(){
  return confirm("Kirim pengajuan tarik gaji sekarang?");
}

(function initThemeToggle(){
  const btn = document.getElementById('theme-toggle');
  const label = document.getElementById('theme-toggle-label');
  if (!btn || !label) return;

  const storageKey = 'gajiku-theme';
  const body = document.body;

  function applyTheme(nextTheme){
    if (nextTheme === 'new') {
      body.classList.add('theme-new');
      label.textContent = 'New Tema';
      btn.setAttribute('aria-pressed', 'true');
      btn.classList.add('active');
    } else {
      body.classList.remove('theme-new');
      label.textContent = 'Legacy';
      btn.setAttribute('aria-pressed', 'false');
      btn.classList.remove('active');
    }
  }

  const saved = localStorage.getItem(storageKey);
  if (saved === 'new' || saved === 'legacy') {
    applyTheme(saved);
  } else {
    applyTheme(body.classList.contains('theme-new') ? 'new' : 'legacy');
  }

  btn.addEventListener('click', function(){
    const nextTheme = body.classList.contains('theme-new') ? 'legacy' : 'new';
    localStorage.setItem(storageKey, nextTheme);
    applyTheme(nextTheme);
  });

  btn.addEventListener('keydown', function(e){
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    btn.click();
  });
})();

(function initPasswordToggle(){
  var toggles = document.querySelectorAll('[data-toggle-password]');
  if (!toggles.length) return;

  toggles.forEach(function(btn){
    var targetId = btn.getAttribute('data-toggle-password');
    var input = document.getElementById(targetId);
    if (!input) return;

    btn.addEventListener('click', function(){
      var showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.setAttribute('aria-pressed', String(!showing));
      btn.setAttribute('aria-label', showing ? 'Tampilkan password' : 'Sembunyikan password');
      var label = btn.querySelector('.password-toggle__text');
      if (label) {
        label.textContent = showing ? 'Tampilkan' : 'Sembunyikan';
      }
    });
  });
})();

(function initResponsiveTables(){
  function textOf(el){
    return (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
  }

  function isActionLabel(label){
    return /^(aksi|action)$/i.test(label || '');
  }

  function cloneCellContent(cell){
    var wrap = document.createDocumentFragment();
    if (!cell) return wrap;

    Array.from(cell.childNodes).forEach(function(node){
      wrap.appendChild(node.cloneNode(true));
    });

    if (!textOf(cell) && !cell.children.length) {
      wrap.appendChild(document.createTextNode('-'));
    }

    return wrap;
  }

  function copyResponsiveData(target, cells){
    cells.forEach(function(cell){
      if (!cell) return;
      if (cell.dataset && cell.dataset.txid) {
        target.dataset.txid = cell.dataset.txid;
      }
    });
  }

  function copyStateClasses(target, cell){
    if (!target || !cell || !cell.classList) return;
    ['ok', 'bad', 'warn'].forEach(function(cls){
      if (cell.classList.contains(cls)) {
        target.classList.add(cls);
      }
    });
  }

  function makePairCell(primaryCell, secondaryCell, primaryLabel, secondaryLabel){
    var item = document.createElement('div');
    item.className = 'mobile-pair-cell';

    if (!secondaryCell) {
      item.classList.add('mobile-pair-cell--single');
    }
    if (isActionLabel(primaryLabel)) {
      item.classList.add('mobile-pair-cell--action');
    }
    copyResponsiveData(item, [primaryCell, secondaryCell]);

    var label = document.createElement('div');
    label.className = 'mobile-pair-label';

    var primaryLabelEl = document.createElement('b');
    primaryLabelEl.className = 'mobile-pair-label-primary';
    primaryLabelEl.textContent = primaryLabel || '';
    label.appendChild(primaryLabelEl);

    if (secondaryLabel) {
      var secondaryLabelEl = document.createElement('span');
      secondaryLabelEl.className = 'mobile-pair-label-secondary';
      secondaryLabelEl.textContent = secondaryLabel;
      label.appendChild(secondaryLabelEl);
    }

    var primaryValue = document.createElement('div');
    primaryValue.className = 'mobile-pair-value-primary';
    copyStateClasses(primaryValue, primaryCell);
    primaryValue.appendChild(cloneCellContent(primaryCell));

    item.appendChild(label);
    item.appendChild(primaryValue);

    if (secondaryCell) {
      var secondaryValue = document.createElement('div');
      secondaryValue.className = 'mobile-pair-value-secondary';
      copyStateClasses(secondaryValue, secondaryCell);
      secondaryValue.appendChild(cloneCellContent(secondaryCell));
      item.appendChild(secondaryValue);
    }

    return item;
  }

  function makeFullCell(cell){
    var item = document.createElement('div');
    item.className = 'mobile-pair-cell mobile-pair-cell--full';
    item.appendChild(cloneCellContent(cell));
    copyResponsiveData(item, [cell]);
    return item;
  }

  function buildMobileTable(table, labels){
    var mobile = document.createElement('div');
    mobile.className = 'mobile-pair-table';

    Array.from(table.querySelectorAll('tbody tr, tfoot tr')).forEach(function(row){
      var cells = Array.from(row.children).filter(function(cell){
        return cell.matches('td, th');
      });
      if (!cells.length) return;

      var mobileRow = document.createElement('div');
      mobileRow.className = 'mobile-pair-row';
      if (row.closest('tfoot')) {
        mobileRow.classList.add('mobile-pair-row--total');
      }

      var labelIndex = 0;
      for (var i = 0; i < cells.length; i += 1) {
        var cell = cells[i];
        var span = Number(cell.getAttribute('colspan') || 1);
        var primaryLabel = labels[labelIndex] || '';

        if (span > 1 || cells.length === 1) {
          mobileRow.appendChild(makeFullCell(cell));
          labelIndex += span;
          continue;
        }

        var nextCell = cells[i + 1];
        var nextSpan = nextCell ? Number(nextCell.getAttribute('colspan') || 1) : 1;
        var secondaryLabel = labels[labelIndex + 1] || '';
        var shouldPair = nextCell && nextSpan === 1 && !isActionLabel(primaryLabel) && !isActionLabel(secondaryLabel);

        if (shouldPair) {
          mobileRow.appendChild(makePairCell(cell, nextCell, primaryLabel, secondaryLabel));
          i += 1;
          labelIndex += 2;
        } else {
          mobileRow.appendChild(makePairCell(cell, null, primaryLabel, ''));
          labelIndex += 1;
        }
      }

      mobile.appendChild(mobileRow);
    });

    return mobile;
  }

  function decorateTable(table){
    if (!table || table.dataset.responsiveReady === '1') return;
    var headerRows = table.tHead ? Array.from(table.tHead.rows) : [];
    if (!headerRows.length) return;

    var headerCells = Array.from(headerRows[headerRows.length - 1].cells);
    var labels = [];
    headerCells.forEach(function(cell){
      var label = textOf(cell);
      var span = Number(cell.getAttribute('colspan') || 1);
      for (var i = 0; i < span; i += 1) {
        labels.push(label);
      }
    });
    if (!labels.length) return;

    Array.from(table.querySelectorAll('tbody tr, tfoot tr')).forEach(function(row){
      var cells = Array.from(row.children).filter(function(cell){
        return cell.matches('td, th');
      });
      var labelIndex = 0;

      cells.forEach(function(cell){
        var span = Number(cell.getAttribute('colspan') || 1);
        if (span > 1 || cells.length === 1) {
          cell.dataset.tableFull = '1';
        }
        if (!cell.dataset.label && span === 1) {
          cell.dataset.label = labels[labelIndex] || '';
        }
        labelIndex += span;
      });
    });

    table.insertAdjacentElement('afterend', buildMobileTable(table, labels));
    table.dataset.responsiveReady = '1';
  }

  function init(){
    Array.from(document.querySelectorAll('table')).forEach(decorateTable);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

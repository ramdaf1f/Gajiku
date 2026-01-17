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

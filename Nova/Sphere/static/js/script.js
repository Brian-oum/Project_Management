// Auto-dismiss alert messages after 5 seconds
document.addEventListener('DOMContentLoaded', function () {
  var alerts = document.querySelectorAll('.sphere-alert');
  alerts.forEach(function (alertEl) {
    setTimeout(function () {
      var bsAlert = bootstrap.Alert.getOrCreateInstance(alertEl);
      bsAlert.close();
    }, 5000);
  });
});

// Sidebar collapse/expand — collapsed (icon-only) by default, expanded
// state persisted in localStorage so it survives page loads/navigation.
document.addEventListener('DOMContentLoaded', function () {
  var toggle = document.getElementById('sphereSidebarToggle');
  if (!toggle) return;

  var html = document.documentElement;

  function setExpanded(expanded) {
    html.classList.toggle('sphere-sidebar-expanded', expanded);
    toggle.classList.toggle('is-active', expanded);
    toggle.setAttribute('aria-expanded', String(expanded));
    try {
      localStorage.setItem('sphere-sidebar-expanded', expanded ? 'true' : 'false');
    } catch (e) {
      /* localStorage unavailable — sidebar just won't remember state */
    }
  }

  // Sync the toggle button's visual state with whatever the pre-paint
  // inline script in base.html already applied to <html>.
  setExpanded(html.classList.contains('sphere-sidebar-expanded'));

  toggle.addEventListener('click', function () {
    setExpanded(!html.classList.contains('sphere-sidebar-expanded'));
  });
});

// Make any table row carrying data-href clickable, without hijacking
// clicks on nested interactive elements (links, buttons, dropdowns).
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('tr[data-href]').forEach(function (row) {
    row.addEventListener('click', function (e) {
      if (e.target.closest('a, button, .dropdown, .dropdown-menu, input, select')) {
        return;
      }
      window.location.href = row.dataset.href;
    });
  });
});
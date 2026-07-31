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
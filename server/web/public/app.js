// SmartClassroom IoT - AngularJS client. Polls the API every 5 s.
// A reading older than this is shown as stale (the Room Pi sends one every 2 s).
var STALE_SECONDS = 30;
// The temperature chart is reloaded every 30 s: it shows one point per minute (decision 3A).
var CHART_REFRESH_MS = 30000;
var CHART_PERIODS = [1, 6, 24];

angular.module('smartRoom', []).controller('MainCtrl', function ($scope, $http, $interval) {
  $scope.status = { state: 'normal', devices: {}, temperature: null, fanSpeed: 0, emergency: null };
  $scope.users = [];
  $scope.emergencies = [];
  $scope.newCard = {};
  $scope.error = null;

  function fail(err) {
    $scope.error = (err.data && err.data.error) || 'Server not reachable';
  }

  function refresh() {
    $http.get('/api/status').then(function (res) {
      $scope.status = res.data;
      $scope.error = null;
    }, fail);
    $http.get('/api/users').then(function (res) { $scope.users = res.data; }, fail);
    $http.get('/api/emergencies').then(function (res) { $scope.emergencies = res.data; }, fail);
  }

  // Readable text for the reason of a call: 'not_evacuated' -> 'not evacuated'.
  $scope.callReason = function (reason) {
    return String(reason).replace(/_/g, ' ');
  };

  // True when the last temperature reading is too old to trust.
  $scope.temperatureStale = function () {
    if (!$scope.status.temperatureTs) {
      return false;
    }
    var age = (Date.now() - new Date($scope.status.temperatureTs).getTime()) / 1000;
    return age > STALE_SECONDS;
  };

  $scope.setFan = function (speed) {
    $http.post('/api/fan', { speed: speed }).then(refresh, fail);
  };

  $scope.unlock = function () {
    $http.post('/api/unlock', {}).then(refresh, fail);
  };

  // Passwords typed for the emergency buttons. They are only sent to Express,
  // which checks them; they are cleared after a correct one (decision 3A).
  $scope.password = { simulate: '', end: '' };

  function emergencyCommand(route, field) {
    $http.post('/api/emergency/' + route, { password: $scope.password[field] }).then(function () {
      $scope.password[field] = '';
      $scope.error = null;
      refresh();
    }, fail);
  }

  $scope.simulateEmergency = function () {
    emergencyCommand('simulate', 'simulate');
  };

  $scope.endEmergency = function () {
    emergencyCommand('end', 'end');
  };

  $scope.addCard = function () {
    $http.post('/api/users', $scope.newCard).then(function () {
      $scope.newCard = {};
      refresh();
    }, fail);
  };

  // --- Temperature chart (Chart.js, served locally from /lib/chartjs) ---
  var chart = null;
  $scope.chartPeriods = CHART_PERIODS;
  $scope.chartHours = CHART_PERIODS[0];
  $scope.chartEmpty = false;

  function hourMinute(ts) {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function drawChart(points) {
    $scope.chartEmpty = points.length === 0;
    var labels = points.map(function (p) { return hourMinute(p.ts); });
    var temps = points.map(function (p) { return p.temp; });
    if (chart) {
      chart.data.labels = labels;
      chart.data.datasets[0].data = temps;
      chart.update();
      return;
    }
    chart = new Chart(document.getElementById('tempChart'), {
      type: 'line',
      data: { labels: labels, datasets: [{ label: '°C', data: temps, borderColor: '#d33', pointRadius: 0, tension: 0.2 }] },
      options: {
        animation: false,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { title: { display: true, text: '°C' } } },
      },
    });
  }

  function loadChart() {
    $http.get('/api/env', { params: { hours: $scope.chartHours } }).then(function (res) {
      drawChart(res.data);
    }, fail);
  }

  $scope.setChartHours = function (hours) {
    $scope.chartHours = hours;
    loadChart();
  };

  refresh();
  $interval(refresh, 5000);
  loadChart();
  $interval(loadChart, CHART_REFRESH_MS);
});

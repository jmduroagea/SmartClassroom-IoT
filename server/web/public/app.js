// SmartClassroom IoT - AngularJS client. Polls the API every 5 s.
// A reading older than this is shown as stale (the Room Pi sends one every 2 s).
var STALE_SECONDS = 30;

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

  refresh();
  $interval(refresh, 5000);
});

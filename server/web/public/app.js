// SmartClassroom IoT - AngularJS client. Polls the API every 5 s.
angular.module('smartRoom', []).controller('MainCtrl', function ($scope, $http, $interval) {
  $scope.status = { devices: {}, temperature: null, fanSpeed: 0 };
  $scope.users = [];
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
  }

  $scope.setFan = function (speed) {
    $http.post('/api/fan', { speed: speed }).then(refresh, fail);
  };

  $scope.unlock = function () {
    $http.post('/api/unlock', {}).then(refresh, fail);
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

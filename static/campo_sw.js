self.addEventListener('push', function(event) {
  let data = {};

  if (event.data) {
    data = event.data.json();
  }

  const title = data.title || 'IRIS';
  const options = {
    body: data.body || 'Nova atualização disponível',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: {
      url: data.url || '/campo/app'
    }
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();

  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});

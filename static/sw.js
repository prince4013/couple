// static/sw.js
// 由 app.py 的 /sw.js 路由從網站根目錄提供，這樣才能控制整個網站（推播＋等待畫面）。

const CACHE_NAME = "qinghua-loading-v1";
const LOADING_URL = "/static/loading.html";
// 頁面超過這麼久還沒回應，就先顯示等待畫面（Render 休眠時會卡幾十秒）。
const SPLASH_DELAY_MS = 2000;
// 等待畫面確認伺服器醒了之後，這段時間內不再擋，避免重新載入又看到等待畫面。
const AWAKE_GRACE_MS = 60000;
let awakeUntil = 0;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.add(LOADING_URL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "server-awake") {
    awakeUntil = Date.now() + AWAKE_GRACE_MS;
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.mode !== "navigate" || req.method !== "GET") return;
  if (new URL(req.url).origin !== self.location.origin) return;

  const network = fetch(req);
  if (Date.now() < awakeUntil) {
    event.respondWith(network);
    return;
  }

  const splash = () => caches.match(LOADING_URL).then((res) => res || network);
  event.respondWith(
    new Promise((resolve) => {
      const timer = setTimeout(() => resolve(splash()), SPLASH_DELAY_MS);
      network
        .then((res) => { clearTimeout(timer); resolve(res); })
        .catch(() => { clearTimeout(timer); resolve(splash()); });
    })
  );
});

self.addEventListener("push", (event) => {
  let payload = { title: "晴話", body: "有新的消息", url: "/home" };
  try {
    if (event.data) {
      payload = { ...payload, ...event.data.json() };
    }
  } catch (e) {
    // 資料不是 JSON 就用預設文字，不讓整個通知失敗
  }

  const options = {
    body: payload.body,
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    vibrate: [200, 100, 200],
    data: { url: payload.url || "/home" },
  };

  event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/home";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});

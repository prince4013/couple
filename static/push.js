// static/push.js
// 負責註冊 Service Worker、跟使用者要通知權限、訂閱 Web Push，
// 並把訂閱資訊送到後端存起來。

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function isPushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function isStandalone() {
  // iOS 只有在「加到主畫面」啟動後才算 standalone，Safari 分頁裡永遠不算。
  return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

async function refreshPushButton() {
  const btn = document.getElementById("push-btn");
  if (!btn) return;

  if (!window.PUSH_ENABLED) {
    btn.textContent = "尚未設定推播（缺少 VAPID 金鑰）";
    btn.disabled = true;
    return;
  }
  if (!isPushSupported()) {
    btn.textContent = "這個瀏覽器不支援推播通知";
    btn.disabled = true;
    return;
  }
  if (isIOS() && !isStandalone()) {
    btn.textContent = "請先「加入主畫面」再啟用通知";
    btn.disabled = false;
    return;
  }

  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      btn.textContent = "通知已啟用 ✓";
      btn.disabled = true;
      return;
    }
  } catch (e) {
    // 忽略，維持預設按鈕文字
  }
  btn.textContent = "啟用想你了 / 留言通知";
  btn.disabled = false;
}

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}

async function enablePush() {
  const btn = document.getElementById("push-btn");
  if (!isPushSupported()) {
    alert("這個瀏覽器不支援推播通知");
    return;
  }
  if (isIOS() && !isStandalone()) {
    alert("iPhone 要先用 Safari 打開這個網站，點分享按鈕選「加入主畫面」，再從主畫面圖示打開 App，才能啟用通知。");
    return;
  }

  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" });
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      alert("沒有取得通知權限，之後可以在系統設定裡重新開啟。");
      return;
    }
    const subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(window.VAPID_PUBLIC_KEY),
    });
    await fetch("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription.toJSON()),
    });
    if (btn) {
      btn.textContent = "通知已啟用 ✓";
      btn.disabled = true;
    }
  } catch (err) {
    console.error("啟用推播失敗", err);
    alert("啟用通知失敗，請確認網站是用 https 開啟的，並稍後再試一次。");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("push-btn");
  if (btn) {
    btn.addEventListener("click", enablePush);
  }
  // 不管推播有沒有開，都註冊 Service Worker，Render 休眠時才有等待畫面。
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" })
      .then(() => migrateOldServiceWorker())
      .catch((err) => console.error("註冊 Service Worker 失敗", err))
      .finally(refreshPushButton);
  } else {
    refreshPushButton();
  }
});

// 以前的 Service Worker 註冊在 /static/sw.js（範圍只有 /static/）。
// 這裡把舊的推播訂閱搬到新的 /sw.js，然後移除舊的，避免通知收到兩次。
async function migrateOldServiceWorker() {
  const newReg = await navigator.serviceWorker.ready; // 等新的 Service Worker 啟用才能訂閱
  const regs = await navigator.serviceWorker.getRegistrations();
  for (const oldReg of regs) {
    if (!new URL(oldReg.scope).pathname.startsWith("/static/")) continue;

    const oldSub = await oldReg.pushManager.getSubscription();
    if (oldSub && window.PUSH_ENABLED && Notification.permission === "granted") {
      try {
        const newSub = await newReg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(window.VAPID_PUBLIC_KEY),
        });
        await fetch("/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newSub.toJSON()),
        });
      } catch (err) {
        // 搬不過去就保留舊的，至少通知還收得到
        console.error("搬移推播訂閱失敗", err);
        continue;
      }
      if (oldSub.endpoint !== (await newReg.pushManager.getSubscription())?.endpoint) {
        await fetch("/push/unsubscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: oldSub.endpoint }),
        });
        await oldSub.unsubscribe();
      }
    }
    await oldReg.unregister();
  }
}

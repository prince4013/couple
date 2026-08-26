# 橘語 · 遠距情侶 App（Flask 示範版）

這是根據介面草稿實作的可執行網頁版原型，使用 Python + Flask，資料庫可選
本機 SQLite 或 Supabase(Postgres)。在同一台電腦（或部署到雲端後）打開
瀏覽器就能操作，右上角「目前身分」可切換成「幸運老婆」或「香噴噴包子」
的視角，模擬兩人各自使用手機的情境。

## 功能對應

- **首頁**：顯示對方所在城市（新竹／Glasgow）的即時時間、自動抓取的天氣、
  今日狀態（可自行新增/刪除狀態選項）；「想你了」按鈕會記錄一筆訊息、
  在支援的手機瀏覽器上觸發震動，並推播通知給對方；見面倒數天數；
  送禮（愛心／蛋糕／咖啡／花束）；最新小問題預覽；最近禮物紀錄。
- **留言**：文字留言 + 圖片上傳，以對話泡泡呈現，新留言會推播通知對方。
- **小問題**：任一方可以提出一個小問題，會建立一個獨立的對話串，
  兩人可以在裡面互相回覆，不會跟一般留言混在一起，新提問/新回覆都會推播通知。
- **清單**：見面前要準備的「要帶的東西」「想去的地方」「想吃的東西」，
  可勾選完成或刪除。
- **回憶相簿**：以時間軸呈現兩人的共同回憶，上傳照片時可以指定日期跟一小段故事，
  最新的日期顯示在最上面、越舊的故事往下捲動才看得到。照片存在 Supabase
  Storage，不會因為 Render 重新部署就不見（設定方式看下面的段落）。
- **動態**：類似小小的部落格 / 動態牆，可以發文字、心情、一張照片，或貼一個
  連結（不限 YouTube，Threads、新聞網站等大部分網站都可以，會自動抓網頁的
  標題跟縮圖，做成像 LINE 那樣的小預覽卡片；如果是 YouTube 連結，卡片上會
  多一個播放鍵圖示，點下去會開新分頁播放）。每篇貼文顯示發文者跟時間，
  另一半可以在下面留言，新貼文/新留言都會推播通知對方。貼文的照片一樣存在
  Supabase Storage。
- **設定**：見面日期、雙方暱稱可編輯；城市與時區已依需求固定為新竹／Glasgow，
  不開放修改；可以啟用/管理即時推播通知；可以一鍵清除「最近的禮物」記錄。

## 安裝與啟動（本機測試）

```bash
cd couple_app
pip install -r requirements.txt
python app.py
```

啟動後打開瀏覽器進入 `http://127.0.0.1:5050`。
第一次執行時會自動建立 `couple_app.db`（SQLite 資料庫）並帶入一組示範資料。

## 部署到網路上（GitHub + Render，兩者都免費）

### 第一步：把專案推上 GitHub

1. 到 GitHub 建立一個新的 repository（例如叫 `couple-app`），設定為 Public 或 Private 都可以。
2. 在本機的 `couple_app` 資料夾裡執行：
   ```bash
   git init
   git add .
   git commit -m "first commit"
   git branch -M main
   git remote add origin https://github.com/你的帳號/couple-app.git
   git push -u origin main
   ```
   （`.gitignore` 已經幫你排除掉資料庫檔、快取檔，不會把測試資料上傳上去）

### 第二步：到 Render 建立 Web Service

1. 用 GitHub 帳號登入 [render.com](https://render.com)。
2. 點選 **New +** → **Web Service**，選擇你剛剛建立的 `couple-app` repository。
3. 設定：
   - **Runtime**：Python 3
   - **Root Directory**：如果你的 GitHub repo 最外層就是 `app.py`、`requirements.txt` 這些檔案，這欄留空；如果 repo 裡還包了一層 `couple_app` 資料夾（也就是路徑長得像 `repo/couple_app/app.py`），這欄要填 `couple_app`，不然 Render 會在錯的資料夾找 `requirements.txt`。
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`python -m gunicorn app:app`
   - **Instance Type**：Free
4. 在 **Environment Variables** 加一組：
   - Key：`SECRET_KEY`，Value：隨便一串英數字亂碼（例如用密碼產生器產生一組，正式上線不要用預設值）。
5. 按下 **Create Web Service**,等它跑完 build 就會拿到一個網址,例如
   `https://couple-app.onrender.com`,兩人手機瀏覽器打開這個網址就能用了。
6. 之後只要在本機改完程式碼、`git push`,Render 就會自動重新部署。

### 常見錯誤：`gunicorn: command not found`

如果 Deploy 的 Logs 出現：
```
bash: line 1: gunicorn: command not found
==> Exited with status 127
```
代表 Start Command 執行時找不到 `gunicorn` 這個指令，通常是下面幾個原因之一：

1. **Root Directory 設錯**：如果你的 GitHub repo 結構是 `repo/couple_app/app.py`
   （也就是 `requirements.txt` 不在 repo 最外層，而是在 `couple_app` 子資料夾裡），
   但 Render 的 **Root Directory** 欄位是空的，Render 就會在錯的資料夾執行
   `pip install -r requirements.txt`，找不到檔案，`gunicorn` 自然也就沒被安裝。
   → 到 Render 的 **Settings → Root Directory**，填上 `couple_app`，存檔後
   會觸發重新部署。
2. **Build 沒有真的跑過 `pip install`**：到 Render 的 **Logs** 分頁，往上捲到
   Build 階段（不是 Deploy 階段），確認有看到
   `Successfully installed ... gunicorn-x.x.x` 這行。如果沒看到，檢查
   **Settings → Build Command** 是不是確實填了 `pip install -r requirements.txt`。
3. **用了舊的 build cache**：到 Render 的 **Manual Deploy** 按鈕旁邊選
   **Clear build cache & deploy**，強制重新安裝一次套件。
4. 這個專案的 Start Command 已經改成 `python -m gunicorn app:app`
   （而不是單純的 `gunicorn app:app`），這樣即使 PATH 設定有問題，
   也會直接用 Build 階段那個 Python 環境裡裝好的 gunicorn 模組來啟動，
   比較不容易再遇到「command not found」。記得到 Render 的
   **Settings → Start Command** 也同步改成這行。

### 重要限制：免費方案的資料不是永久保存的（如果沒有接 Supabase）

Render 的免費方案沒有「持久化磁碟」,代表每次重新部署(你 push 新程式碼)或
容器被重建時,如果還是用內建的 SQLite,資料庫檔案會被重置成初始的示範資料,
留言、禮物紀錄、清單都會消失。**這個專案已經支援直接接 Supabase 的
免費 Postgres 資料庫來解決這個問題**,做法看下面這段。

## 接上 Supabase（讓資料永久保存）

這個 App 已經內建雙資料庫支援：只要有設定 `DATABASE_URL` 這個環境變數,
就會自動改用 Postgres(Supabase);沒有設定的話就用本機的 SQLite,
所以你在自己電腦測試時完全不受影響。

### 第一步：在 Supabase 建立專案

1. 登入 [supabase.com](https://supabase.com),點 **New Project**。
2. 幫專案取名、設定一組資料庫密碼(記得存起來,等一下會用到)、選一個離你近的 Region。
3. 專案建立好之後,到左側選單 **Project Settings → Database**。
4. 找到 **Connection string** 區塊,選 **URI** 分頁,你會看到類似這樣的字串：
   ```
   postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
   ```
   把 `[YOUR-PASSWORD]` 換成你剛剛設定的資料庫密碼。
   建議選 **Connection pooling**(通常是 6543 埠、網址裡有 `pooler`)這個版本,
   比較適合像 Render 這種外部服務連線,連線數限制也比較寬鬆。

### 第二步：在 Render 加上環境變數

回到 Render 的 Web Service 頁面 → **Environment**,新增一組：
- Key：`DATABASE_URL`
- Value：剛剛從 Supabase 複製、換好密碼的那串連線字串

存檔後 Render 會自動重新部署。這次啟動時,App 會偵測到 `DATABASE_URL`
存在,自動改用 Supabase 的 Postgres 建表、寫入初始資料,之後不管你重新
部署幾次,留言、禮物紀錄、小問題、清單都會留在 Supabase 裡,不會再被清空。

你也可以到 Supabase 左側選單的 **Table Editor**,直接用瀏覽器看到
`users`、`messages`、`gifts`、`questions` 等資料表跟裡面的內容。

### 接上 Supabase Storage（讓回憶相簿的照片永久保存）

回憶相簿的照片一定要存在 Supabase Storage，不能存在 Render 本機磁碟
（原因跟前面資料庫一樣：Render 免費方案的磁碟不是永久的）。設定方式：

1. 在你剛剛建立的 Supabase 專案裡，左側選單點 **Storage**。
2. 點 **New bucket**，Bucket name 填 `memories`（要跟這個字一模一樣，
   或是填別的名字但要記得，等一下環境變數要對應）。
3. 建立的時候把 **Public bucket** 打開（設成公開）。這個 App 的做法是
   後端用 service_role 金鑰上傳照片、前端直接用公開網址顯示照片，
   設成公開 bucket 最簡單；缺點是知道網址的人都能看到照片，
   對一個兩人使用的私密相簿來說通常還好，但如果你介意，之後可以
   再改成私有 bucket + 簽名網址（做法比較複雜，需要的話再跟我說）。
4. 到 Supabase 左側選單 **Project Settings → API**，找到
   **Project URL** 和 **service_role secret** 這兩個值。
   ⚠️ `service_role` 金鑰權限很大，等同於後端管理員權限，絕對不要
   放到前端程式碼或公開的地方，只能放在 Render 的環境變數裡。
5. 到 Render 的 Web Service → **Environment**，新增兩組：
   - Key：`SUPABASE_URL`，Value：剛剛複製的 Project URL
     （長得像 `https://xxxxxxxxxxxx.supabase.co`）
   - Key：`SUPABASE_SERVICE_KEY`，Value：剛剛複製的 service_role 金鑰
6. 存檔後 Render 會自動重新部署。之後在「回憶相簿」頁面上傳照片，
   就會自動存到 Supabase Storage，重新部署也不會消失。

如果沒有設定這兩個環境變數，「回憶相簿」和「動態」頁面的照片上傳表單會被
停用並顯示提示訊息，不影響其他功能正常使用；「留言」頁面則會退回存在
Render 本機磁碟（重新部署後會消失，跟一開始沒接 Supabase 時一樣）。

留言、回憶相簿、動態這三個地方的圖片，現在都已經統一走 Supabase Storage，
只要設定好上面這兩個環境變數，三個地方上傳的照片都不會因為 Render
重新部署而消失。

## 設定推播通知（Web Push，讓對方即時收到通知）

這個 App 已經內建完整的推播通知功能：對方送禮物、留言、問小問題、回覆的時候，
另一邊的手機會跳出通知（如果瀏覽器/系統支援，也會震動）。設定分成三步：

### 第一步：設定 VAPID 金鑰

推播通知需要一組專屬的「簽名金鑰」(VAPID)，代表是你的 App 在發送通知，
不是別人冒充的。我已經幫你產生好一組可以直接使用：

```
VAPID_PUBLIC_KEY=BKqA6gvlcAFZk52GZUGS71E8hwq8RICQhOT3PlTuee5sVENxRxNdCB6Q6c_-8r9OEQaCig6WogXk7kORokouRPg
VAPID_PRIVATE_KEY=jDQcHnTHAXFP7OBu4p3Mw000ltv9JmsoxYO_rnHc_GE
```

到 Render 的 **Environment**，新增三組環境變數：
- Key：`VAPID_PUBLIC_KEY`，Value：上面那串（`BKqA...` 開頭）
- Key：`VAPID_PRIVATE_KEY`，Value：上面那串（`jDQc...` 開頭）
- Key：`VAPID_CLAIM_EMAIL`，Value：隨便填一個你的信箱，例如 `you@example.com`

⚠️ `VAPID_PRIVATE_KEY` 也是機密資料，只放在 Render 環境變數裡，不要
commit 進 GitHub。如果你想之後自己換一組新的，專案裡有附
`generate_vapid_keys.py`，本機執行 `python generate_vapid_keys.py`
就會印出一組新的金鑰。

### 第二步：iPhone 這邊要「加入主畫面」

這是最關鍵的一步，也是 iOS 系統本身的硬性規定，沒有辦法繞過：
**iPhone 只有在網站被「加入主畫面」、從主畫面的圖示打開之後，才能收到
推播通知；單純在 Safari 分頁裡打開網站是收不到通知的**，這跟這個 App
寫得好不好沒有關係，是蘋果從 iOS 16.4 開始定的規則。

對方（用 iPhone 的那位）要做的事：
1. 用 **Safari**（不是 Chrome）打開你的網址，例如 `https://couple-app.onrender.com`
2. 點下方工具列中間的「分享」按鈕（正方形加箭頭的圖示）
3. 往下找到 **加入主畫面**，點下去，右上角按「新增」
4. 回到手機桌面，會看到一個新的 App 圖示（愛心圖案）
5. **改成從這個桌面圖示打開 App**，之後都固定從這裡打開

### 第三步：在 App 裡啟用通知

1. 從主畫面圖示打開 App 之後，切到「設定」頁
2. 找到「即時通知」卡片，點「啟用想你了 / 留言通知」
3. iOS 會跳出系統的通知權限詢問，點「允許」
4. 按鈕會變成「通知已啟用 ✓」，代表設定成功

兩人都要各自做一次「加入主畫面 + 啟用通知」，才能互相收到對方的通知。
Android 手機用 Chrome 打開網站就可以直接啟用，不需要加入主畫面這一步。

### 關於震動的實話

即使照著上面設定完成，iOS 的通知本身還是會顯示、會有系統提示音，
但 iOS Safari 對於推播通知裡「自訂震動節奏」的支援目前不完整，
所以震動的「感覺」可能跟 Android 不會完全一樣（大致上還是會依照
iPhone 系統的通知震動設定），這是 Apple 平台本身的限制，不是這個 App
可以完全控制的部分。但「對方按了想你了、你會即時收到通知」這件事，
設定完成後就能正常運作了。

## 目前的限制（之後可以擴充的方向）

- 這是單一伺服器的示範版，兩個身分是用「目前身分」切換模擬，還不是
  真正的雙帳號登入。推播通知已經做好了，但因為沒有帳號系統，是靠瀏覽器
  分別記住「你訂閱的裝置」來區分兩人，兩人要各自在自己的手機上啟用一次。
- 目前是網頁版（PWA）；如果之後想要上架到 App Store / Google Play 的
  原生 App，可以把這份 Flask 後端改成純 API，前端用 Flutter、
  React Native 或 SwiftUI / Kotlin 重寫，原生 App 對震動、推播的
  控制會比網頁版更完整（尤其是 iOS）。
- 留言、回憶相簿、動態的圖片都已經統一走 Supabase Storage，只要設定好
  `SUPABASE_URL` 和 `SUPABASE_SERVICE_KEY`，就不會因為 Render 重新部署
  而消失；沒設定的話，留言圖片會退回存在 Render 本機磁碟（重新部署後會
  消失），回憶相簿跟動態的照片上傳表單則會直接停用。
- 「動態」裡的連結預覽是抓網頁的 `og:title` / `og:image` 標籤，大部分
  網站（Threads、新聞網站等）都適用，但少數網站可能沒有這些標籤或會
  擋掉伺服器的請求，這種情況下卡片只會顯示網域名稱，沒有標題或縮圖，
  屬於正常降級行為，不是錯誤。
- 天氣資料來自 Open-Meteo，是免費、不需金鑰的公開氣象 API；
  如果之後想要更詳細的天氣資訊（例如未來預報、空氣品質），
  可以再串接 OpenWeatherMap 等其他服務。
- 推播通知在這個沙盒開發環境裡沒辦法連到 Apple/Google 的真實推播伺服器
  做測試，程式邏輯（訂閱寫入資料庫、送禮/留言時查訂閱並呼叫 webpush）
  已經用模擬資料測試過沒問題，但建議部署後兩支手機各自啟用通知，
  實際點一次「想你了」互相測試看看，如果沒收到通知，把 Render 的
  Logs 貼給我，我可以幫你看是哪個環節出問題。

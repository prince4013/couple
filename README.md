# 橘語 · 遠距情侶 App（Flask 示範版）

這是根據介面草稿實作的可執行網頁版原型，使用 Python + Flask，資料庫可選
本機 SQLite 或 Supabase(Postgres)。在同一台電腦（或部署到雲端後）打開
瀏覽器就能操作，右上角「目前身分」可切換成「幸運老婆」或「香噴噴包子」
的視角，模擬兩人各自使用手機的情境。

## 功能對應

- **首頁**：顯示對方所在城市（新竹／Glasgow）的即時時間、自動抓取的天氣、
  今日狀態；「想你了」按鈕會記錄一筆訊息並在支援的手機瀏覽器上觸發震動；
  見面倒數天數；送禮（愛心／蛋糕／咖啡）；最新小問題預覽；最近禮物紀錄。
- **留言**：文字留言 + 圖片上傳，以對話泡泡呈現。
- **小問題**：任一方可以提出一個小問題，會建立一個獨立的對話串，
  兩人可以在裡面互相回覆，不會跟一般留言混在一起。
- **清單**：見面前要準備的「要帶的東西」與「想去的地方」，可勾選完成或刪除。
- **設定**：見面日期、雙方姓名可編輯；城市與時區已依需求固定為新竹／Glasgow，不開放修改。

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

### 目前還沒解決的部分

圖片上傳(留言裡的照片)目前還是存在 Render 本機磁碟上,所以就算接了
Supabase 的資料庫,圖片本身在重新部署後還是會不見。如果你想讓照片也
永久保存,可以之後再串接 **Supabase Storage**(它本身就有提供免費的
物件儲存空間),需要調整 `/messages` 路由把圖片改成上傳到 Supabase
而不是存本機 —— 如果你想做這一步,再跟我說,我可以幫你加上去。

## 目前的限制（之後可以擴充的方向）

- 這是單一伺服器的示範版，兩個身分是用「目前身分」切換模擬，
  還不是真正的雙帳號登入 / 雙手機即時同步。要做到「A 按了想你了，
  B 的手機立刻收到通知並震動」，需要加上使用者帳號系統
  （例如 Flask-Login）+ 推播通知（Web Push 或原生 App 的 Push Notification）。
- 目前是網頁版；如果要包裝成手機 App（iOS / Android，並支援真正的
  裝置震動與推播），建議之後用這份 Flask 後端 API 化，
  前端改用 Flutter、React Native 或 SwiftUI / Kotlin 開發原生介面。
- 圖片上傳目前存在 Render 本機磁碟，重新部署後會消失；解法寫在上面
  「接上 Supabase」段落的最後一小節（可以再串接 Supabase Storage）。
- 天氣資料來自 Open-Meteo，是免費、不需金鑰的公開氣象 API；
  如果之後想要更詳細的天氣資訊（例如未來預報、空氣品質），
  可以再串接 OpenWeatherMap 等其他服務。

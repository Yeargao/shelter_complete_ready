# AI 智慧工具與手機介面

新增 /ai-tools。管理者可使用四項工具；照護人員只能搜尋自己被指派的任務回報／異常。既有 LightGBM / CatBoost 不參與新工具。

## 功能與限制
- 語意搜尋：比對最近最多 80 筆非空白照護／異常備註，回傳原始紀錄、動物編號、任務 ID、日期與相似分數。使用本機 Embedding 或經授權的 Gemini Embedding；均不可用時明確標示字元及同義詞比對。不是全庫 RAG 生成回答。
- 資料品質：檢查疫苗日期、驅蟲紀錄、健康狀態與未結案異常，以及資源設定；Isolation Forest 只處理至少 20 筆且有足夠變異的同物種數值組。資料是設定／估算而非實測；所有結果均需人工核對。可選擇啟用 Gemini 文字矛盾核對。
- 排程：比較同一日期起算七天的原始平衡、緊急優先、最少異動策略，重用原硬限制、預覽／版本核對／套用機制。指標為實際求解結果，非完成率或保證最佳；三個方案可能相同。若資料版本不同需重新預覽。
- 照片：比對目前可讀的任務照片與資料庫內嵌圖片（最多 80 張），包含已離所動物。可設定本機 CLIP；預設使用感知雜湊及色彩特徵。為防止任意 URL 存取，外部網址不由伺服器抓取，會顯示略過數。相似分數非身份機率，不能自動合併動物。沒有照片時如實顯示無法比對。
- 手機：680px 以下切換頂部可捲動導覽、觸控按鈕與照護任務清單；保留管理者日曆及原有手動指派表單，桌面版維持原布局。

## 啟用真正的語意模型與影像模型
現有服務可以直接執行本機降級功能，沒有新模型下載或外部費用。若允許將照護備註傳到 Gemini，必須同時設定 LLM_ENABLED=1、LLM_DATA_APPROVED=1、SHELTER_AI_NOTES_APPROVED=1、GEMINI_API_KEY，並確認模型可用與配額。此設定會讓經授權的備註及查詢文字離開伺服器。不得為未授權真實資料開啟。圖片不傳外部服務。

若要使用本機預訓練模型，在後端主機的 Python 環境安裝以下選用依賴並預先下載模型（需要網路與磁碟空間）：

    cd backend
    python -m pip install -r requirements-ai-local.txt
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5').save('local-models/text')"
    python -c "from transformers import CLIPModel,CLIPProcessor; m='openai/clip-vit-base-patch32'; CLIPModel.from_pretrained(m).save_pretrained('local-models/clip'); CLIPProcessor.from_pretrained(m).save_pretrained('local-models/clip')"

PowerShell（從 backend 啟動）：

    $env:SHELTER_TEXT_MODEL_DIR = (Resolve-Path ./local-models/text).Path
    $env:SHELTER_CLIP_MODEL_DIR = (Resolve-Path ./local-models/clip).Path
    python -m uvicorn main:app --host 127.0.0.1 --port 8001

模型需由部署者自行配置；不將模型檔或 API key 提交 GitHub。可在 AI 頁面看到實際使用模式。建議先用示範資料檢查模型記憶體、搜尋品質與影像誤匹配。若需要在手機與電腦同一區網測試，Vite 使用 npm run dev -- --host 0.0.0.0，再以電腦區網 IP:8000 開啟；正式網站同一網址即可。

## 驗收
從專案根目錄：

    python -m unittest discover -s tests -p test_ai_tools.py -v
    python -m unittest discover -s tests -p test_weekly_schedule.py -v
    cd frontend
    npm ci
    npm run build

手動驗收：以管理者與照護人員登入，測試資料權限、無備註／無照片、降級提示、排程版本變動及確認後套用，並在 390px、680px、1280px 視窗確認導覽、回報、表單及日曆。

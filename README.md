# VM Controller (Cloud Run)

Cloud Run から Google Compute Engine の VM を **/vm/start**, **/vm/stop** で操作する最小API。

## エンドポイント
- `POST /vm/start?instance=<NAME>&zone=<ZONE>`  
- `POST /vm/stop?instance=<NAME>&zone=<ZONE>`  
- `GET  /healthz`

## 事前準備（GCP）
1. プロジェクトで **Compute Engine API** と **Cloud Run API** を有効化
2. Cloud Run 用のサービスアカウントを作成し、ロール:
   - `roles/compute.instanceAdmin.v1`
3. Cloud Run でこのコンテナをデプロイし、**サービスアカウントに上記ロール**を割当
4. Cloud Run の環境変数に以下を設定
   - `PROJECT_ID` = `your-project-id`
   - `ZONE`       = 例: `asia-northeast1-b`
   - `INSTANCE`   = 既定のVM名（固定しないなら空でOK）

## テスト (curl)
```bash
POST {SERVICE_URL}/vm/start?instance=<NAME>&zone=<ZONE>
POST {SERVICE_URL}/vm/stop?instance=<NAME>&zone=<ZONE>
GET  {SERVICE_URL}/healthz
```

## セキュリティ
- MVPでは「認証なし」を許可してまず動作確認 → 本番は **認証必須** に変更し、IAP/IDトークン/独自APIキーなどで保護してください。
- IAMは**最小権限**。必要に応じて特定インスタンスのみ操作可の運用ルールを中継側で実装してください。

## 使い方の流れ
1. このファイルを**GitHub に push**
2. **Cloud Build（GUI）**でGitHub連携→トリガ作成（Dockerfileモード）→**Build 実行**
3. **Artifact Registry** に画像が登録される
4. **Cloud Run（GUI）**で「既存コンテナからデプロイ」→**環境変数**と**サービスアカウント**を設定
5. `POST /vm/start` / `POST /vm/stop` で動作確認

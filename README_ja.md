# Nature Remo - Home Assistant カスタム統合

⭐ この統合が役に立った場合は、GitHubでスターを付けていただけると嬉しいです。

Nature RemoをHome Assistantに連携するためのカスタムインテグレーションです。  
エアコンや照明の操作、温度・湿度などの情報をHome Assistant上でまとめて扱えるようになります。

---

## ⚠️ ご注意
このカスタムインテグレーションは、Nature社およびHome Assistantの**非公式**な統合です。  
利用にあたっては、**自己責任で**ご使用いただきますようお願いいたします。

---

## 主な機能

- Nature Remoに登録された家電（エアコン・照明）の操作
- 温度・湿度・照度・人感センサーのデータ取得
- Nature Remo E / E Liteによるスマートメーターの電力データ取得
- カスタムサービスによる照明の詳細な制御（モード指定など）
- signals に基づいて生成されたリモートエンティティを使って IR コマンドを送信
- 対応エアコンを Nature Remo ローカルAPI 経由でLAN内から直接IR制御（任意）

---

## インストール方法（HACS）

以下のボタンをクリックすると、HACSにこのリポジトリを簡単に追加できます。

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=NaNaLinks&repository=homeassistant_nature_remo&category=integration)

1. Home AssistantでHACSを開きます
2. 右上のメニュー（⋮）をクリックします
3. 「Custom repositories」を選択します
4. 以下のリポジトリURLを追加します  
   https://github.com/NaNaLinks/homeassistant_nature_remo  
   カテゴリは「Integration」を選択してください
5. 「Nature Remo」をインストールします
6. Home Assistantを再起動します

---

## インストール方法（手動）

1. 本リポジトリを以下のパスに配置してください：

```
<設定フォルダ>/custom_components/nature_remo/
```

2. Home Assistantを再起動してください。

---

## セットアップ手順

1. Home Assistantの「設定 → デバイスとサービス → 統合を追加」から `Nature Remo` を選択します。
2. アクセストークン（APIキー）と統合の名前を入力します。
   - トークンは [Nature公式サイト](https://home.nature.global) から発行できます。
3. 登録済みのデバイスや家電が自動的に追加されます。

---

## オプション設定

- データの更新間隔（秒単位）を指定できます。
  - デフォルトは `60秒` に設定されています。

⚠️ Nature Remo Cloud API にはリクエスト制限があります。  
更新間隔を短く設定しすぎると、APIの制限に達する可能性があります。

---

## 対応エンティティ一覧

| 種類    | 説明                                                              |
|---------|-------------------------------------------------------------------|
| climate | エアコンの操作（冷房・暖房・除湿など）                           |
| light   | 照明の操作（オン／オフ、モード切替）                              |
| sensor  | 温度、湿度、照度、人感、電力（買電／売電）                        |
| remote  | IR／AC／LIGHTのアプライアンスに定義された signals を送信できる   |

※ 今後、さらに対応デバイスやエンティティを拡張予定です。

---

## サンプル：リモートエンティティの使い方

Nature Remoに定義された `signals` 情報をもとに `remote` エンティティが生成されます。  
Home Assistant上から `remote.send_command` を使って信号を送信できます。

### 例：サービス呼び出し

以下のように `remote.send_command` を使って信号を送信します：

```yaml
service: remote.send_command
target:
  entity_id: remote.living_room_remote  # リモートエンティティID
data:
  command: "電源"  # Remoに登録されたボタン名
```

---

## 外部温度・湿度センサーの利用

デバイスごとに外部の温度・湿度センサーを設定できるようになりました。

Home Assistantの設定画面からエンティティを選択することで、Nature Remoのデフォルト値ではなく、指定したセンサーの値を使用することができます。

### 使い方

- Home Assistantの統合設定を開く
- 対象デバイスを選択
- 温度・湿度のエンティティを選択
- 設定を保存

設定後は、以下に反映されます：

- climateエンティティの温度・湿度表示
- エアコン制御に使用される環境データ

### 注意事項

- 外部センサーが未設定の場合は、従来通りNature Remoの値を使用します
- 温度・湿度の値を持つ任意のセンサーエンティティを使用できます

---

## ローカルIR制御（任意・実験的）

エアコンをクラウドではなく Nature Remo のローカルAPI（`POST http://<RemoのIP>/messages`）で
**LAN内から直接**操作できます。統合がエアコンの全状態をIRフレームにエンコードして送るため、
高速・インターネット不要で、クラウドのレート制限や温度刻みなどの値チェックの影響を受けません。

対応しているローカルIRプロトコル:

| プロトコル        | 対象エアコン                                                  |
|-------------------|---------------------------------------------------------------|
| `fujitsu_arrff2j` | 富士通ゼネラル（nocria）リモコン AR-RFF2J（AEHA・16バイト） |

### 設定方法

1. ルーターで Nature Remo のIPアドレスを固定（DHCP予約）します。
2. *設定 → デバイスとサービス → Nature Remo → 設定* で:
   - `<Remo名> ：IPアドレス` に Remo のIP（例 `192.168.10.150`。`http://host` 形式も可）
   - `Nature Remo <エアコン名> ：ローカルIRプロトコル（none=クラウド）` で `fujitsu_arrff2j` を選択
   - 任意: `<Remo名> ：ローカルAPIでリモコン操作を検知（/messagesをポーリング）`（既定OFF、後述）
3. 統合を再読み込み（⋮ → 再読み込み）するか Home Assistant を再起動します。

Nature Remo nano はローカルAPIに対応していません。

### 動作

- 操作ごとに全状態を含むフレームを1回送信します（タイムアウト約3秒）。電源ONビットは
  OFFからONにする時だけ立てます。
- ローカル送信に失敗した場合（タイムアウト・接続エラー・2xx以外）はクラウドAPIで送信し、警告をログに出します。
- 温度は0.5℃刻み（16〜30℃、冷房は18〜30℃）。モードは 切/冷房/暖房/除湿/自動（送風はこのプロトコルでは表現不可）。
- 状態は楽観的（IRには応答がない）で、再起動後に復元されます。ローカル送信はクラウドに反映されないため、
  クラウドのエアコン設定は変化した時（Natureアプリで操作した等）のみ採用し、ローカル送信後60秒間は無視します。
- climate エンティティの追加属性: `local_protocol`、`local_host`、`last_command_path`（`local`/`cloud`/`remote_ir`）、
  `last_local_error`、`last_remote_ir`。

### リモコン操作の検知（任意）

有効にすると `GET /messages` を2秒ごとにポーリングします。Remo は最後に受信したIR信号だけを
（時刻なしで）保持するため、信号が変化して有効なフレームとしてデコードできた時に操作として扱います。制限:

- Remo がリモコンのIRを受光できる位置にある必要があります。
- ポーリング間隔内の複数操作は最後の1つだけ検知されます（毎回全状態を送るプロトコルなので最終状態は正しくなります）。
  全く同じ操作の繰り返しは検知できません（状態は変わらないので無害）。
- 同じRemoで同じプロトコルのエアコンが2台以上ある場合は区別できないため無視します。別の部屋の同型エアコンの操作を拾う可能性があります。
- 起動後最初のポーリングは基準値としてのみ使います。

---

## 作者情報

- 作成者：[@nanosns](https://github.com/nanosns) (NaNaRin)
- 所属・運営：[@NaNaLinks](https://github.com/NaNaLinks)
- SNS： [note](https://note.com/nanomana)

---

## ライセンス

MIT License
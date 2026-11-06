# Football schedule

欧州5大リーグとCLの日程・結果・順位表を日本時間で表示する静的サイトです。
クラブ名は英語です。「すべて」は6大会の次節をまとめて表示します。

## GitHub Pages

Settings → Pages → Source を GitHub Actions に設定します。
mainへのpushで Deploy website が検証・公開します。

Settings → Secrets and variables → Actions に FOOTBALL_DATA_API_KEY を登録してください。
キーをソース・チャット・ログへ書かないでください。
Update match data は3時間ごと（UTC 00:17から3時間間隔）に取得・検証・更新・公開します。
手動実行にも対応しています。API通信は7秒間隔です。
失敗した大会の既存データを保持し、更新失敗をActionsで報告します。
取得確認ファイルはキャッシュとPagesに保存し、Git履歴へは含めません。
GitHubによる定期実行は遅延することがあり、Publicリポジトリで60日間活動がない場合は停止される場合があります。

## ローカル確認

```sh
python -m unittest discover -s tests
node tests/app.test.cjs
python scripts/check_release.py
python scripts/build_public.py
python -m http.server 8000 --directory public
```

http://localhost:8000/site/ を開いてください。
データ提供: https://www.football-data.org/

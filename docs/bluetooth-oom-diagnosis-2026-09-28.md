# Raspberry Pi Zero W Bluetooth 調査（2026-09-28）

## 観測した事実

- Home Assistant 2025.11.3 が Bluetooth management socket への `LOAD_CONN_PARAM` 送信時に `OSError: [Errno 12] Out of memory` を記録した。2026-09-23、24、25、28 に発生。
- 物理メモリの `MemAvailable` は約 220 MiB あり、OOM Killer の履歴はない。
- `bluetoothd` 5.82 は BLE 接続と切断を繰り返し、`No matching connection for device` を多数記録。2026-09-28 07:36:11 に SIGSEGV で異常終了し、自動再起動した。
- hci0 は bcm43438-bt。Home Assistant はアクティブスキャンを要求してもパッシブスキャンから戻らない修復通知を出した。

## 原因の見立て

Linux の [Bluetooth management command completion](https://codebrowser.dev/linux/linux/net/bluetooth/mgmt_util.c.html) は受信ソケットへ結果をキューイングする。そのキューがソケットの `sk_rcvbuf` に達した場合、[`sock_queue_rcv_skb`](https://codebrowser.dev/linux/linux/net/core/sock.c.html) は `-ENOMEM` を返す。今回の `Errno 12` は物理メモリ不足よりも、管理ソケットの受信キュー満杯で説明しやすい。ただし発生時のカーネルトレースは取得できておらず、確定ではない。BlueZ の SIGSEGV は別途調査が必要。

## 適用した緩和策

- ホストの `/etc/sysctl.d/90-home-assistant-bluetooth.conf` で `net.core.rmem_default = 1048576` を設定し、Home Assistant を再起動した。従来値は 180224。コンテナ内で新しく開いた Bluetooth management socket の `SO_RCVBUF=1048576` を確認した。
- `sock:sock_rcvqueue_full` トレースポイントを有効化し、再発時に受信キュー満杯だったか確認できるようにした。トレースは `/sys/kernel/tracing/trace`、有効化スイッチは `/sys/kernel/tracing/events/sock/sock_rcvqueue_full/enable`。
- SESAME 通知購読に 20 秒のタイムアウトを追加し、購読が固まっても他のデバイスを待たせ続けないようにした。
- この Home Assistant バージョンには存在しない `async_request_active_scan` の呼び出しを、`async_process_advertisements` に置き換えた。

日次更新確認の負荷は当初疑ったが、更新確認を止めた状態でも `Errno 12` が再発したため設定を元に戻した。

## 検証と残件

- 修正した Python ファイルのコンパイル、通知購読タイムアウト時の切断、広告待機 API の呼び出しを確認した。
- Home Assistant 再起動後、ロックの状態が 07:46:05 に `locked` として Recorder に記録され、Bluetooth の修復通知も issue registry から消えていた。物理的な解錠操作は実施していない。
- `Errno 12` の発生間隔は数時間から 1 日程度。短時間の正常動作だけで再発防止を確定できない。次回発生時には Home Assistant ログの時刻と `sock_rcvqueue_full` トレースを照合する。
- BlueZ が再び SIGSEGV になる、または SESAME 状態通知が復旧しない場合は、hci0 の完全な電源断を含む機器側の復旧が必要となる可能性がある。

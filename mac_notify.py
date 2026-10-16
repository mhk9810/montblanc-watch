#!/usr/bin/env python3
"""맥에서 ntfy 알림 채널을 듣고 있다가, 알림이 오면 맥 알림 + 소리를 띄우고 예약 페이지를 연다.
launchd(~/Library/LaunchAgents/com.hyeabin.montblanc-notify.plist)가 항상 켜둔다."""
import json
import subprocess
import time
import urllib.request

from check import NTFY_TOPIC


def notify(title, msg, url=None):
    subprocess.run(["osascript",
                    "-e", "on run argv",
                    "-e", 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
                    "-e", "end run", title, msg])
    if url:
        subprocess.run(["open", url])


def main():
    since = str(int(time.time()))
    while True:
        try:
            url = f"https://ntfy.sh/{NTFY_TOPIC}/json?since={since}"
            with urllib.request.urlopen(url, timeout=90) as r:
                for line in r:
                    ev = json.loads(line)
                    if ev.get("event") != "message":
                        continue
                    since = ev["id"]
                    print(f"알림: {ev.get('title')} | {ev.get('message')}", flush=True)
                    notify(ev.get("title", "몽블랑 알리미"), ev.get("message", ""), ev.get("click"))
        except Exception as e:
            print(f"연결 끊김, 다시 연결: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()

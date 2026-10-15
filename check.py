#!/usr/bin/env python3
"""몽블랑 산장 2027년 6월 예약 오픈 감시기 (GitHub Actions에서 5분마다 실행).

- TMB 공식 사이트(Nant Borrant, La Nova): 달력의 2027년 6월 칸 상태를 읽어서
  'Close'가 아닌 칸이 하나라도 생기면 = 예약 오픈으로 판단.
- Rifugio Bonatti: 예약 폼 날짜칸의 막힌 기간(data-disable-range)에서
  2027년 6월 날짜가 하나라도 풀리면 = 예약 오픈으로 판단.
결과는 docs/status.json과 ntfy 상태 채널(웹사이트가 읽음)에 남기고, 상태가 바뀌면 ntfy로 푸시.
--serve N 으로 실행하면 N초 동안 웹사이트의 "지금 확인하기" 신호를 기다렸다가 바로 확인한다.
"""
import html
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

STATUS = Path(__file__).resolve().parent / "docs" / "status.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"
KST = timezone(timedelta(hours=9))

TMB = {
    "Nant Borrant": "https://www.montourdumontblanc.com/en/refuges/refuge-de-nant-borrant",
    "La Nova": "https://www.montourdumontblanc.com/en/refuges/auberge-refuge-de-la-nova",
}
BONATTI = "https://www.rifugiobonatti.it/en/book-now/"
# 알림 채널 (ntfy.sh 웹/앱에서 구독)
NTFY_TOPIC = "montblanc-2027-3ecf3d6f"
STATUS_TOPIC = NTFY_TOPIC + "-status"  # 매 확인 결과 (웹사이트가 읽음)
TRIGGER_TOPIC = NTFY_TOPIC + "-check"  # 웹사이트 "지금 확인하기" 버튼 신호


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def june_2027(page):
    """{'02/06/2027': 'Close', ...}"""
    return dict(re.findall(r'title="(\d{2}/06/2027) — ([^"]+)"', page))


def bonatti_june(page):
    """체크인 칸의 막힌 기간을 읽어 (6월에 열린 날짜 목록, 막힌 기간 원문)을 돌려준다."""
    m = re.search(r'name="date-1"[^>]*data-disable-range="([^"]*)"', page)
    if not m:
        return None, None
    raw = html.unescape(m.group(1))
    ranges = []
    for part in filter(None, (x.strip() for x in raw.split(","))):
        a, b = (datetime.strptime(x.strip(), "%m/%d/%Y").date() for x in part.split(" - "))
        ranges.append((a, b))
    june = [date(2027, 6, d) for d in range(1, 31)]
    free = [d for d in june if not any(a <= d <= b for a, b in ranges)]
    return free, raw


def push(title, msg, url=None, topic=NTFY_TOPIC, priority=5):
    """ntfy.sh로 푸시. 탭하면 url이 열린다."""
    body = {"topic": topic, "title": title, "message": msg, "priority": priority}
    if url:
        body["click"] = url
    try:
        req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"[ntfy] 푸시 실패: {e}")


def check_once():
    old = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    old_refuges = old.get("refuges", {})
    now = datetime.now(KST)
    new = {"refuges": {}, "bonatti": old.get("bonatti", {})}

    for name, url in TMB.items():
        prev = old_refuges.get(name, {})
        try:
            cells = june_2027(fetch(url))
        except Exception as e:
            print(f"[{name}] 가져오기 실패: {e}")
            new["refuges"][name] = prev
            continue
        if not cells:
            print(f"[{name}] 6월 달력을 못 찾음 (사이트 구조 변경?)")
            new["refuges"][name] = {**prev, "status": "unknown", "url": url}
            continue
        days = {d[:2]: s for d, s in sorted(cells.items())
                if s.strip().lower() not in ("close", "closed")}
        status = "open" if days else "closed"
        print(f"[{name}] 6월 상태: {status} {days}")
        entry = {"status": status, "days": days, "url": url + "#calendrier",
                 "since": prev.get("since") if prev.get("status") == status else now.isoformat()}
        if status == "open" and prev.get("status") != "open":
            summary = ", ".join(f"{d}일 {s}" for d, s in list(days.items())[:8])
            push(f"🏔 {name} 6월 예약 열림!", summary, entry["url"])
        new["refuges"][name] = entry

    prev = old.get("bonatti", {})
    try:
        free, raw = bonatti_june(fetch(BONATTI))
        if free is None:
            print("[Bonatti] 날짜칸 설정을 못 찾음 (사이트 구조 변경?)")
            new["bonatti"] = {**prev, "status": "unknown", "url": BONATTI}
        else:
            status = "open" if free else "closed"
            print(f"[Bonatti] 6월 상태: {status} (막힌 기간: {raw})")
            days = {f"{d.day:02d}": "선택 가능" for d in free}
            if status == "open" and prev.get("status") != "open":
                push("🏔 Bonatti 6월 예약 열림!", f"6월 {free[0].day}일~{free[-1].day}일 선택 가능", BONATTI)
            new["bonatti"] = {"status": status, "days": days, "blocked": raw, "url": BONATTI,
                              "since": prev.get("since") if prev.get("status") == status else now.isoformat()}
    except Exception as e:
        print(f"[Bonatti] 가져오기 실패: {e}")
        new["bonatti"] = prev

    live = {"checked_at": now.isoformat(), **{k: new[k] for k in ("refuges", "bonatti")}}
    push("status", json.dumps(live, ensure_ascii=False, separators=(",", ":")),
         topic=STATUS_TOPIC, priority=1)

    # 결과가 같으면 하루 한 번만 커밋 (저장소가 비활성으로 꺼지지 않게)
    new["checked_date"] = now.strftime("%Y-%m-%d")
    if new != old:
        STATUS.parent.mkdir(exist_ok=True)
        STATUS.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n")


def wait_trigger(since, until):
    """until까지 버튼 신호를 기다린다. 신호가 오면 그 메시지 id, 아니면 None."""
    while time.time() < until:
        try:
            url = f"https://ntfy.sh/{TRIGGER_TOPIC}/json?since={since}"
            with urllib.request.urlopen(url, timeout=60) as r:
                for line in r:
                    ev = json.loads(line)
                    if ev.get("event") == "message":
                        return ev["id"]
                    if time.time() >= until:
                        return None
        except Exception:
            time.sleep(3)
    return None


def serve(seconds, every=300):
    """seconds 동안 every초마다 확인하고, 그 사이 버튼 신호가 오면 바로 확인한다."""
    end = time.time() + seconds
    since = int(time.time())
    while time.time() < end:
        check_once()
        next_check = min(time.time() + every, end)
        while (msg_id := wait_trigger(since, next_check)):
            print("[버튼] 지금 확인하기 요청")
            since = msg_id
            check_once()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
    else:
        check_once()

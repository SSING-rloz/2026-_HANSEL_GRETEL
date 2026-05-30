#!/usr/bin/env python3
# monitor.py  --  조종 노트북에서 실행 (사슬의 한쪽 끝, 상류 없음)
#
# 노드1에서 홉을 거쳐 중계되어 올라온 '모든 노드'의 RSSI를 실시간으로 표시하고,
# STOP 시 올라오는 CSV들을 received/ 폴더에 저장합니다.
#
# START/STOP 을 보내기 전에 먼저 켜 두세요.  종료: Ctrl+C

import socket, json, os, threading, time
from datetime import datetime

TELEM_PORT = 5051   # 실시간 RSSI 수신(UDP)
FILE_PORT  = 5053   # CSV 수신(TCP)
STALE_SEC  = 5.0    # 이 시간 넘게 소식 없으면 (no resp) 표시
REFRESH    = 0.5    # 화면 갱신 주기(초)

nodes = {}
lock = threading.Lock()


def telem_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", TELEM_PORT))
    while True:
        data, addr = s.recvfrom(2048)
        try:
            m = json.loads(data.decode())
            nid = str(m["node_id"])
            with lock:
                prev = nodes.get(nid, {})
                nodes[nid] = {"rssi": m.get("rssi"), "ts": m.get("ts"),
                              "last": time.time(), "ip": addr[0],
                              "count": prev.get("count", 0) + 1}
        except Exception:
            pass


def file_server():
    os.makedirs("received", exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", FILE_PORT))
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=save_file, args=(conn,), daemon=True).start()


def save_file(conn):
    with conn:
        buf = b""
        while b"\n" not in buf:
            d = conn.recv(4096)
            if not d:
                return
            buf += d
        line, rest = buf.split(b"\n", 1)
        try:
            meta = json.loads(line.decode())
        except Exception:
            return
        size, fname = meta.get("size", 0), meta.get("filename", "unknown.csv")
        path = os.path.join("received", os.path.basename(fname))
        with open(path, "wb") as f:
            f.write(rest)
            got = len(rest)
            while got < size:
                d = conn.recv(min(8192, size - got))
                if not d:
                    break
                f.write(d)
                got += len(d)
        print(f"\n[FILE] 수신 완료: {path}  ({got} bytes)")


def main():
    threading.Thread(target=telem_listener, daemon=True).start()
    threading.Thread(target=file_server, daemon=True).start()
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            now = time.time()
            print("  실시간 RSSI 모니터        " + datetime.now().strftime("%H:%M:%S"))
            print("  " + "-" * 56)
            print(f"  {'node':>5} {'RSSI(dBm)':>10} {'updated':>12} {'samples':>9} {'IP':>16}")
            with lock:
                items = sorted(nodes.items())
            if not items:
                print("\n  (수신 대기 중...  노드에서 데이터가 오면 표시됩니다)")
            for nid, v in items:
                age = now - v["last"]
                rssi = "--" if v["rssi"] is None else v["rssi"]
                upd = "(no resp)" if age > STALE_SEC else f"{age:0.1f}s ago"
                print(f"  {nid:>5} {str(rssi):>10} {upd:>12} {v['count']:>9} {v['ip']:>16}")
            print("\n  START/STOP 은 control.py 로.  Ctrl+C 로 종료.")
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        print("\n종료.")


if __name__ == "__main__":
    main()

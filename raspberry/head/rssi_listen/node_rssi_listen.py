#!/usr/bin/env python3
# node.py  --  라즈베리파이 노드(노드1~N) 및 AP/헤드(라즈4)에서 실행
#
# 선형 릴레이: 각 노드는 '이웃 두 개'하고만 통신합니다.
#   상류(UP)  = 노트북(조종) 방향 이웃
#   하류(DOWN) = AP(헤드) 방향 이웃
#
#   - 명령(START/STOP) : 상류에서 받아 실행 + 하류로 그대로 전달
#   - 실시간 RSSI       : 내 값을 상류로 전송 + 하류에서 온 것을 상류로 중계
#   - CSV(STOP 시)      : 내 파일을 상류로 전송 + 하류에서 온 파일도 상류로 중계
#                         (홉을 거쳐 결국 노트북까지 올라감)
#
# 실행:  python3 node.py <NODE_ID> <상류_IP> [하류_IP]
#   예) 노드1 :  python3 node.py 1 <노트북_IP> <노드2_IP>
#       노드2 :  python3 node.py 2 <노드1_IP>  <노드3_IP>
#       노드N :  python3 node.py N <노드N-1_IP> <AP_IP>
#       AP    :  python3 node.py AP <노드N_IP>            (하류 없음 → 비움)

import socket, subprocess, csv, json, os, re, sys, time, threading
from datetime import datetime, timezone, timedelta

# ===== 설정 =====
NODE_ID = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NODE_ID", "1")
UP_IP   = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("UP_IP", "")     # 노트북 방향 이웃 (필수)
DOWN_IP = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("DOWN_IP", "")   # AP 방향 이웃 (헤드/AP는 비움)
IFACE   = os.environ.get("IFACE", "wlan0")

TELEM_PORT = 6001   # UDP, 상류로 흐르는 실시간 RSSI
CMD_PORT   = 6002   # UDP, 하류로 흐르는 명령
FILE_PORT  = 6003   # TCP, 상류로 흐르는 CSV
SAMPLE_SEC = 0.2    # 측정 주기(초). 0.2 = 5Hz
KST = timezone(timedelta(hours=9))

state = {"logging": False, "csv_path": None, "csv_file": None, "writer": None}
lock = threading.Lock()


def read_rssi():
    """RSSI(dBm) 정수를 반환. 실패 시 None."""
    for args in (["iw", "dev", IFACE, "link"], ["iw", "dev", IFACE, "station", "dump"]):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=1).stdout
            m = re.search(r"signal:\s*(-?\d+)", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    return None


def send_upstream_file(header, data):
    """헤더(JSON+개행) + 파일 바이트를 상류 이웃의 FILE_PORT로 전송(TCP)."""
    if not UP_IP:
        print("[FILE] 상류 없음(헤드?) — 전송 생략, 로컬 보관")
        return
    with socket.create_connection((UP_IP, FILE_PORT), timeout=5) as s:
        s.sendall(header)
        s.sendall(data)


def start_logging():
    with lock:
        if state["csv_file"]:
            state["csv_file"].close()
        os.makedirs("rssi_logs", exist_ok=True)
        ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
        path = os.path.join("rssi_logs", f"node{NODE_ID}_{ts}.csv")
        f = open(path, "w", newline="")
        w = csv.writer(f)
        w.writerow(["timestamp_kst", "node_id", "rssi_dbm"])
        state.update(logging=True, csv_path=path, csv_file=f, writer=w)
    print(f"[START] 로깅 시작 -> {path}")


def stop_logging_and_send():
    with lock:
        if not state["csv_file"]:
            print("[STOP] 로깅 중이 아님 (무시)")
            return
        state["csv_file"].close()
        path = state["csv_path"]
        state.update(logging=False, csv_file=None, writer=None)
    print(f"[STOP] 로깅 종료 -> {path}")
    try:
        with open(path, "rb") as fp:
            data = fp.read()
        header = json.dumps({"node_id": NODE_ID,
                             "filename": os.path.basename(path),
                             "size": len(data)}).encode() + b"\n"
        send_upstream_file(header, data)
        print("[FILE] 내 CSV 상류 전송 완료 (로컬에도 보관됨)")
    except Exception as e:
        print(f"[FILE] 전송 실패({e}); 파일은 로컬 보관: {path}")


def file_server():
    """하류에서 올라온 CSV를 받아 그대로 상류로 중계."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", FILE_PORT))
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=relay_file, args=(conn,), daemon=True).start()


def relay_file(conn):
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
        size, data = meta.get("size", 0), rest
        while len(data) < size:
            d = conn.recv(min(8192, size - len(data)))
            if not d:
                break
            data += d
    try:
        send_upstream_file(line + b"\n", data)
        print(f"[FILE] 중계: node{meta.get('node_id')} 파일을 상류로")
    except Exception as e:
        print(f"[FILE] 중계 실패({e})")


def cmd_listener():
    """상류에서 온 명령을 실행하고 하류로 전달."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", CMD_PORT))
    while True:
        data, _ = s.recvfrom(1024)
        cmd = data.decode(errors="ignore").strip().upper()
        if cmd == "START":
            start_logging()
        elif cmd == "STOP":
            stop_logging_and_send()
        if DOWN_IP:
            try:
                s.sendto(data, (DOWN_IP, CMD_PORT))
            except Exception:
                pass


def telem_forwarder():
    """하류에서 온 실시간 RSSI를 그대로 상류로 중계."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", TELEM_PORT))
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        data, _ = s.recvfrom(2048)
        if UP_IP:
            try:
                out.sendto(data, (UP_IP, TELEM_PORT))
            except Exception:
                pass


def main():
    threading.Thread(target=cmd_listener, daemon=True).start()
    threading.Thread(target=telem_forwarder, daemon=True).start()
    threading.Thread(target=file_server, daemon=True).start()
    live = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"node{NODE_ID} 실행 (iface={IFACE}, 상류={UP_IP or '-'}, 하류={DOWN_IP or '-'}, {1/SAMPLE_SEC:.0f}Hz)")
    try:
        while True:
            rssi = read_rssi()
            ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            if UP_IP:                                   # 내 RSSI를 상류로
                msg = json.dumps({"node_id": NODE_ID, "rssi": rssi, "ts": ts}).encode()
                try:
                    live.sendto(msg, (UP_IP, TELEM_PORT))
                except Exception:
                    pass
            if state["logging"]:                        # START~STOP 구간만 로깅
                with lock:
                    if state["writer"]:
                        state["writer"].writerow([ts, NODE_ID, "" if rssi is None else rssi])
                        state["csv_file"].flush()
            time.sleep(SAMPLE_SEC)
    except KeyboardInterrupt:
        with lock:
            if state["csv_file"]:
                state["csv_file"].close()
        print("\n종료.")


if __name__ == "__main__":
    main()

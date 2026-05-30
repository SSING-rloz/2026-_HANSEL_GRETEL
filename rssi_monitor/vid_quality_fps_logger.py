#!/usr/bin/env python3
# fps_logger.py  --  조종 노트북에서 실행
#
# 헤드(AP)에서 릴레이로 올라온 H.264 영상을 디코딩해서, 1초 단위로
#   [KST 시각, 디코딩 FPS, 디코드 에러 수] 를 CSV에 기록합니다.
# 영상 품질 저하 시각을 RSSI 로그와 (절대 시각 기준으로) 맞춰 비교하는 용도입니다.
#
# 핵심: 디코드는 별도 스레드에서 프레임 수를 세고, 메인 타이머가 1초마다 기록합니다.
#       => 스트림이 멈추면 그 구간은 fps=0 으로 기록됩니다(프리즈 감지).
#
# 사전: pip install av
#
# 실행:  python3 fps_logger.py "<영상 입력>"
#   입력 예시(파이프라인에 맞게):
#     - MPEG-TS over UDP :  "udp://@0.0.0.0:5000"
#     - RTP/SDP 파일     :  "stream.sdp"
#     - RTSP             :  "rtsp://<AP_IP>:8554/cam"
#     - 테스트용 파일     :  "sample.mp4"
#   인자 생략 시 기본값 "udp://@0.0.0.0:5000" 사용.

import av, csv, os, sys, time, threading
from datetime import datetime, timezone, timedelta

INPUT        = sys.argv[1] if len(sys.argv) > 1 else "udp://@0.0.0.0:5050"
LOG_INTERVAL = 1.0
KST = timezone(timedelta(hours=9))

# 저지연 UDP 수신용 옵션 (입력 형식에 따라 무시될 수 있음)
OPTS = {"fflags": "nobuffer", "flags": "low_delay",
        "fifo_size": "5000000", "overrun_nonfatal": "1"}

counter = {"frames": 0, "errors": 0}
clock_lock = threading.Lock()
running = True


def decode_worker():
    global running
    while running:
        try:
            container = av.open(INPUT, options=OPTS, timeout=10)
        except Exception as e:
            print(f"[FPS] 입력 열기 실패({e}) — 2초 후 재시도")
            time.sleep(2)
            continue
        try:
            vstream = container.streams.video[0]
        except Exception:
            print("[FPS] 비디오 스트림 없음 — 재시도")
            try: container.close()
            except Exception: pass
            time.sleep(2)
            continue
        print(f"[FPS] 입력 연결됨: {INPUT}")
        try:
            for packet in container.demux(vstream):
                if not running:
                    break
                try:
                    for _ in packet.decode():
                        with clock_lock:
                            counter["frames"] += 1
                except Exception:
                    with clock_lock:
                        counter["errors"] += 1
        except Exception as e:
            print(f"[FPS] 스트림 중단({e}) — 재연결")
        finally:
            try: container.close()
            except Exception: pass
        time.sleep(1)


def main():
    global running
    os.makedirs("fps_logs", exist_ok=True)
    start_ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    path = os.path.join("fps_logs", f"fps_{start_ts}.csv")

    threading.Thread(target=decode_worker, daemon=True).start()

    print(f"[FPS] 로깅 시작 -> {path}   (Ctrl+C 로 종료)")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_kst", "fps", "decode_errors"])
        f.flush()
        t0 = time.time()
        try:
            while True:
                time.sleep(LOG_INTERVAL)
                now = time.time()
                with clock_lock:
                    frames = counter["frames"]
                    errors = counter["errors"]
                    counter["frames"] = 0
                    counter["errors"] = 0
                fps = frames / (now - t0) if now > t0 else 0.0
                t0 = now
                ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                w.writerow([ts, round(fps, 2), errors])
                f.flush()
                print(f"  {ts}   fps={fps:5.1f}   decode_err={errors}")
        except KeyboardInterrupt:
            running = False
            print("\n종료.")


if __name__ == "__main__":
    main()

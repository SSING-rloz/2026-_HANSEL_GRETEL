#!/usr/bin/env python3
import json
import os
import socket
import sys
import time
from typing import Optional

# ============================================================
# rssi_to_head_detach_sender.py
#
# 실행 위치:
#   통신부 코드가 실행되는 곳
#
# 목적:
#   통신부가 RSSI/링크 상태를 판단한 뒤 특정 유닛 detach가 필요하다고
#   판단하면, 각 Node로 직접 detach_press를 보내지 않고 HEAD Pi의
#   head_detach_router.py로 detach request를 보낸다.
#
# AP IP:
#   HEAD  = 192.168.4.1
#   NODE1 = 192.168.4.11
#   NODE2 = 192.168.4.12
#   NODE3 = 192.168.4.13
#
# 최종 흐름:
#   통신부 RSSI 판단
#   -> request_detach_from_head("NODE2")
#   -> HEAD_IP:6000
#   -> head_detach_router.py
#   -> NODE1_IP:5000 으로 detach_press
#   -> NODE1 마이크로서보 작동
#   -> NODE2 분리
# ============================================================

HEAD_DETACH_ROUTER_IP = os.environ.get("HEAD_DETACH_ROUTER_IP", os.environ.get("HEAD_IP", "192.168.4.1"))
HEAD_DETACH_ROUTER_PORT = int(os.environ.get("HEAD_DETACH_ROUTER_PORT", "6000"))

UDP_SEND_REPEAT = int(os.environ.get("DETACH_REQUEST_SEND_REPEAT", "3"))
UDP_REPEAT_DELAY = float(os.environ.get("DETACH_REQUEST_REPEAT_DELAY", "0.03"))

VALID_TARGETS = {"NODE1", "NODE2", "NODE3"}


def normalize_target(target_unit: str) -> str:
    target = str(target_unit).strip().upper().replace("-", "_").replace(" ", "_")

    aliases = {
        "NODE1": "NODE1",
        "NODE_1": "NODE1",
        "NODE1_PI": "NODE1",
        "NODE1PI": "NODE1",
        "NODE2": "NODE2",
        "NODE_2": "NODE2",
        "NODE2_PI": "NODE2",
        "NODE2PI": "NODE2",
        "NODE3": "NODE3",
        "NODE_3": "NODE3",
        "NODE3_PI": "NODE3",
        "NODE3PI": "NODE3",
    }

    normalized = aliases.get(target)

    if normalized is None:
        raise ValueError(f"unsupported detach target: {target_unit}")

    return normalized


def request_detach_from_head(
    target_unit: str,
    reason: str = "rssi_degraded",
    rssi_dbm: Optional[float] = None,
    degraded_count: Optional[int] = None,
    ok_count: Optional[int] = None,
) -> bool:
    target = normalize_target(target_unit)

    message = {
        "type": "detach_request",
        "target": target,
        "guard_status": "detach_candidate",
        "reason": reason,
    }

    if rssi_dbm is not None:
        message["rssi_dbm"] = rssi_dbm

    if degraded_count is not None:
        message["degraded_count"] = degraded_count

    if ok_count is not None:
        message["ok_count"] = ok_count

    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for _ in range(UDP_SEND_REPEAT):
                sock.sendto(payload, (HEAD_DETACH_ROUTER_IP, HEAD_DETACH_ROUTER_PORT))
                time.sleep(UDP_REPEAT_DELAY)

        print(f"[DETACH REQUEST] target={target} -> HEAD {HEAD_DETACH_ROUTER_IP}:{HEAD_DETACH_ROUTER_PORT}")
        return True

    except Exception as e:
        print(f"[DETACH REQUEST FAIL] target={target} / {e}")
        return False


def send_guard_status_to_head(
    station: str,
    guard_status: str,
    reason: str = "rssi_guard",
    rssi_dbm: Optional[float] = None,
    degraded_count: Optional[int] = None,
    ok_count: Optional[int] = None,
) -> bool:
    status = str(guard_status).strip().lower().replace("-", "_").replace(" ", "_")

    if status == "detach_candidate":
        return request_detach_from_head(
            station,
            reason=reason,
            rssi_dbm=rssi_dbm,
            degraded_count=degraded_count,
            ok_count=ok_count,
        )

    target = normalize_target(station)

    message = {
        "type": "guard_status",
        "target": target,
        "guard_status": status,
        "reason": reason,
    }

    if rssi_dbm is not None:
        message["rssi_dbm"] = rssi_dbm

    if degraded_count is not None:
        message["degraded_count"] = degraded_count

    if ok_count is not None:
        message["ok_count"] = ok_count

    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (HEAD_DETACH_ROUTER_IP, HEAD_DETACH_ROUTER_PORT))
        return True
    except Exception as e:
        print(f"[GUARD STATUS SEND FAIL] target={target}, status={status} / {e}")
        return False


def handle_guard_result(
    station: str,
    guard_status: str,
    reason: str = "rssi_guard",
    rssi_dbm: Optional[float] = None,
    degraded_count: Optional[int] = None,
    ok_count: Optional[int] = None,
) -> bool:
    """
    기존 통신부 코드에서 아래처럼 쓰면 된다.

        degraded_count, ok_count, guard_status = update_guard_state(...)
        handle_guard_result(
            station,
            guard_status,
            rssi_dbm=current_rssi,
            degraded_count=degraded_count,
            ok_count=ok_count,
        )

    station은 반드시 '분리 대상 유닛'이어야 한다.
      NODE1 -> HEAD가 분리서보 작동
      NODE2 -> NODE1이 분리서보 작동
      NODE3 -> NODE2가 분리서보 작동
    """
    return send_guard_status_to_head(
        station,
        guard_status,
        reason=reason,
        rssi_dbm=rssi_dbm,
        degraded_count=degraded_count,
        ok_count=ok_count,
    )


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 rssi_to_head_detach_sender.py NODE1")
        print("  python3 rssi_to_head_detach_sender.py NODE2")
        print("  python3 rssi_to_head_detach_sender.py NODE3")
        sys.exit(1)

    target = sys.argv[1]
    ok = request_detach_from_head(target, reason="manual_cli_test")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import json
import os
import socket
import time
from typing import Optional, Tuple

# ============================================================
# head_detach_router.py
#
# 실행 위치:
#   HEAD Pi
#
# 목적:
#   통신부가 RSSI/링크 상태를 판단한 뒤 "어떤 유닛을 분리해야 하는지"를
#   HEAD Pi로 보낸다.
#
#   HEAD Pi의 이 라우터는 받은 target을 보고 실제 detach 서보를 움직일
#   actuator 유닛을 결정한 뒤, 해당 유닛의 control server(UDP 5000)로
#   "detach_press"를 보낸다.
#
# 기구 매핑:
#   NODE1 분리 -> HEAD  detach servo 작동
#   NODE2 분리 -> NODE1 detach servo 작동
#   NODE3 분리 -> NODE2 detach servo 작동
#
# 통신부 -> HEAD router 메시지 예:
#   NODE1,detach_candidate
#   NODE2,detach_candidate
#   NODE3,detach_candidate
#   detach NODE2
#   node3_detach
#   {"target":"NODE2","guard_status":"detach_candidate","reason":"rssi_degraded"}
#   {"detach_target":"NODE3"}
#
# 이 라우터 -> 각 유닛 control server:
#   detach_press\n  -> actor_ip:5000
# ============================================================


# =========================
# IP / port settings
# =========================

HEAD_IP = os.environ.get("HEAD_IP", "127.0.0.1")
NODE1_IP = os.environ.get("NODE1_IP", "10.180.86.224")
NODE2_IP = os.environ.get("NODE2_IP", "10.180.86.161")
NODE3_IP = os.environ.get("NODE3_IP", "10.180.86.242")

ROBOT_CONTROL_PORT = int(os.environ.get("ROBOT_CONTROL_PORT", "5000"))

ROUTER_HOST = os.environ.get("DETACH_ROUTER_HOST", "0.0.0.0")
ROUTER_PORT = int(os.environ.get("DETACH_ROUTER_PORT", "6000"))
ROUTER_BUFFER_SIZE = int(os.environ.get("DETACH_ROUTER_BUFFER_SIZE", "2048"))


# =========================
# Reliability settings
# =========================

UDP_SEND_REPEAT = int(os.environ.get("DETACH_SEND_REPEAT", "3"))
UDP_REPEAT_DELAY = float(os.environ.get("DETACH_REPEAT_DELAY", "0.03"))

# 같은 target에 대해 반복 detach 방지
ONE_SHOT_PER_TARGET = os.environ.get("ONE_SHOT_PER_TARGET", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

DETACH_COOLDOWN_SEC = float(os.environ.get("DETACH_COOLDOWN_SEC", "3600"))

# 통신부에서 recovered가 오면 해당 target의 one-shot 잠금을 풀지 여부
RESET_ON_RECOVERED = os.environ.get("RESET_ON_RECOVERED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)


# =========================
# Unit names
# =========================

HEAD = "HEAD"
NODE1 = "NODE1"
NODE2 = "NODE2"
NODE3 = "NODE3"

VALID_UNITS = {HEAD, NODE1, NODE2, NODE3}

UNIT_IP = {
    HEAD: HEAD_IP,
    NODE1: NODE1_IP,
    NODE2: NODE2_IP,
    NODE3: NODE3_IP,
}

# 핵심 매핑:
# 분리 대상 target을 보고 실제 detach_press를 받을 actor를 결정한다.
DETACH_ACTUATOR_BY_TARGET = {
    NODE1: HEAD,
    NODE2: NODE1,
    NODE3: NODE2,
}

DETACH_STATUS_WORDS = {
    "detach_candidate",
    "detach",
    "drop",
    "drop_candidate",
    "node_drop",
    "separate",
    "separation",
    "link_degraded",
    "degraded",
}

IGNORE_STATUS_WORDS = {
    "watching",
    "recovered",
    "link_ok",
    "ok",
    "normal",
}

detached_targets = set()
last_detach_time_by_target = {}


# =========================
# Utility
# =========================

def normalize_unit(value: object) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip().upper()
    text = text.replace("-", "_")
    text = text.replace(" ", "_")

    aliases = {
        "HEAD": HEAD,
        "HEAD_PI": HEAD,
        "HEADPI": HEAD,

        "NODE1": NODE1,
        "NODE_1": NODE1,
        "NODE1_PI": NODE1,
        "NODE1PI": NODE1,

        "NODE2": NODE2,
        "NODE_2": NODE2,
        "NODE2_PI": NODE2,
        "NODE2PI": NODE2,

        "NODE3": NODE3,
        "NODE_3": NODE3,
        "NODE3_PI": NODE3,
        "NODE3PI": NODE3,
    }

    return aliases.get(text)


def normalize_status(value: object) -> Optional[str]:
    if value is None:
        return None

    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def is_detach_status(status: Optional[str]) -> bool:
    return normalize_status(status) in DETACH_STATUS_WORDS


def is_ignore_status(status: Optional[str]) -> bool:
    return normalize_status(status) in IGNORE_STATUS_WORDS


# =========================
# Message parsing
# =========================

def parse_json_message(raw_message: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        data = json.loads(raw_message)
    except Exception as e:
        print(f"[PARSE] JSON error: {e}")
        return None, None, None

    target_value = (
        data.get("detach_target")
        or data.get("target_unit")
        or data.get("target")
        or data.get("station")
        or data.get("node")
        or data.get("unit")
        or data.get("detach_unit")
    )

    actor_value = (
        data.get("detach_actor")
        or data.get("actor")
        or data.get("actuator")
        or data.get("actuator_unit")
        or data.get("servo_unit")
    )

    status_value = (
        data.get("guard_status")
        or data.get("status")
        or data.get("state")
        or data.get("command")
        or data.get("action")
    )

    target = normalize_unit(target_value)
    actor = normalize_unit(actor_value)
    status = normalize_status(status_value)

    # target 또는 actor만 보내도 detach 요청으로 처리
    if status is None and (target is not None or actor is not None):
        status = "detach_candidate"

    return target, actor, status


def parse_text_message(raw_message: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    cleaned = raw_message.strip()

    if cleaned == "":
        return None, None, None

    compact = (
        cleaned.upper()
        .replace("-", "_")
        .replace(" ", "_")
        .replace(",", "_")
        .replace(":", "_")
        .replace(";", "_")
        .replace("=", "_")
    )

    direct_target_patterns = {
        "HEAD_DETACH": HEAD,
        "DETACH_HEAD": HEAD,
        "HEAD_DROP": HEAD,
        "DROP_HEAD": HEAD,

        "NODE1_DETACH": NODE1,
        "DETACH_NODE1": NODE1,
        "NODE1_DROP": NODE1,
        "DROP_NODE1": NODE1,

        "NODE2_DETACH": NODE2,
        "DETACH_NODE2": NODE2,
        "NODE2_DROP": NODE2,
        "DROP_NODE2": NODE2,

        "NODE3_DETACH": NODE3,
        "DETACH_NODE3": NODE3,
        "NODE3_DROP": NODE3,
        "DROP_NODE3": NODE3,
    }

    for pattern, unit in direct_target_patterns.items():
        if pattern in compact:
            return unit, None, "detach_candidate"

    tmp = cleaned
    for delimiter in [",", ":", ";", "="]:
        tmp = tmp.replace(delimiter, " ")

    parts = [p.strip() for p in tmp.split() if p.strip()]

    if len(parts) == 1:
        target = normalize_unit(parts[0])
        if target is not None:
            return target, None, "detach_candidate"
        return None, None, None

    target = None
    actor = None
    status = None

    for idx, part in enumerate(parts):
        key = part.strip().lower().replace("-", "_")
        next_value = parts[idx + 1] if idx + 1 < len(parts) else None

        if key in ("target", "station", "node", "unit", "detach_target", "detach_unit", "target_unit"):
            target = normalize_unit(next_value)
            continue

        if key in ("actor", "actuator", "detach_actor", "servo_unit", "actuator_unit"):
            actor = normalize_unit(next_value)
            continue

        maybe_unit = normalize_unit(part)
        if maybe_unit is not None and target is None:
            target = maybe_unit

        maybe_status = normalize_status(part)
        if maybe_status in DETACH_STATUS_WORDS or maybe_status in IGNORE_STATUS_WORDS:
            status = maybe_status

    if status is None and (target is not None or actor is not None):
        status = "detach_candidate"

    return target, actor, status


def parse_message(raw_message: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    raw_message = raw_message.strip()

    if raw_message == "":
        return None, None, None

    if raw_message.startswith("{"):
        return parse_json_message(raw_message)

    return parse_text_message(raw_message)


# =========================
# Detach routing
# =========================

def actor_from_target_or_actor(target: Optional[str], actor: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if actor is not None:
        if actor not in VALID_UNITS:
            return None, f"unsupported actor={actor}"
        return actor, f"actor explicitly requested: {actor}"

    if target is None:
        return None, "missing target"

    if target == HEAD:
        return None, "HEAD is not a detachable downstream target in this router"

    actuator = DETACH_ACTUATOR_BY_TARGET.get(target)

    if actuator is None:
        return None, f"no actuator mapping for target={target}"

    return actuator, f"target={target} -> actuator={actuator}"


def send_detach_press_to_actor(actor: str) -> bool:
    actor_ip = UNIT_IP.get(actor)

    if actor_ip is None or str(actor_ip).strip() == "":
        print(f"[SEND] actor={actor} has empty IP")
        return False

    message = b"detach_press\n"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for _ in range(UDP_SEND_REPEAT):
                sock.sendto(message, (actor_ip, ROBOT_CONTROL_PORT))
                time.sleep(UDP_REPEAT_DELAY)

        print(f"[SEND] detach_press -> {actor} {actor_ip}:{ROBOT_CONTROL_PORT}")
        return True

    except Exception as e:
        print(f"[SEND FAIL] detach_press -> {actor} {actor_ip}:{ROBOT_CONTROL_PORT} / {e}")
        return False


def handle_recovered(target: Optional[str], actor: Optional[str]) -> str:
    if target is not None and RESET_ON_RECOVERED:
        detached_targets.discard(target)
        last_detach_time_by_target.pop(target, None)
        return f"recovered: reset target={target}"

    if actor is not None and RESET_ON_RECOVERED:
        # actor만 들어오면 이 actor가 담당하는 target을 찾아서 reset
        for target_unit, actuator_unit in DETACH_ACTUATOR_BY_TARGET.items():
            if actuator_unit == actor:
                detached_targets.discard(target_unit)
                last_detach_time_by_target.pop(target_unit, None)
        return f"recovered: reset actor={actor}"

    return "recovered: no action"


def handle_detach_request(target: Optional[str], actor: Optional[str], status: Optional[str], raw_message: str) -> str:
    status = normalize_status(status)

    if is_ignore_status(status):
        return handle_recovered(target, actor)

    if not is_detach_status(status):
        return f"ignored: unsupported status={status}"

    actor_unit, reason = actor_from_target_or_actor(target, actor)

    if actor_unit is None:
        return f"ignored: {reason}"

    dedupe_key = target if target is not None else f"ACTOR:{actor_unit}"
    now = time.time()

    if ONE_SHOT_PER_TARGET and dedupe_key in detached_targets:
        return f"ignored: already triggered for {dedupe_key}"

    last_time = last_detach_time_by_target.get(dedupe_key, 0.0)
    if last_time > 0 and now - last_time < DETACH_COOLDOWN_SEC:
        remaining = DETACH_COOLDOWN_SEC - (now - last_time)
        return f"ignored: cooldown for {dedupe_key}, remaining={remaining:.1f}s"

    print("====================================")
    print("[DETACH ROUTER] Detach request accepted")
    print(f"[DETACH ROUTER] raw={raw_message!r}")
    print(f"[DETACH ROUTER] target={target}, actor={actor_unit}, status={status}")
    print(f"[DETACH ROUTER] reason={reason}")
    print("====================================")

    ok = send_detach_press_to_actor(actor_unit)

    if ok:
        detached_targets.add(dedupe_key)
        last_detach_time_by_target[dedupe_key] = now
        return f"triggered: target={target}, actor={actor_unit}"

    return f"failed: target={target}, actor={actor_unit}"


# =========================
# Main
# =========================

def print_startup():
    print("====================================")
    print(" HANSEL Head Detach Router")
    print("====================================")
    print(f"LISTEN              = {ROUTER_HOST}:{ROUTER_PORT}/udp")
    print(f"ROBOT_CONTROL_PORT  = {ROBOT_CONTROL_PORT}/udp")
    print("------------------------------------")
    print("UNIT IPs:")
    print(f"  HEAD  = {HEAD_IP}")
    print(f"  NODE1 = {NODE1_IP}")
    print(f"  NODE2 = {NODE2_IP}")
    print(f"  NODE3 = {NODE3_IP}")
    print("------------------------------------")
    print("Mechanical detach mapping:")
    print("  target NODE1 -> actor HEAD")
    print("  target NODE2 -> actor NODE1")
    print("  target NODE3 -> actor NODE2")
    print("------------------------------------")
    print("Accepted messages:")
    print("  NODE1,detach_candidate")
    print("  NODE2,detach_candidate")
    print("  NODE3,detach_candidate")
    print('  {"target":"NODE2","guard_status":"detach_candidate"}')
    print('  {"detach_target":"NODE3"}')
    print("====================================")


def main():
    print_startup()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((ROUTER_HOST, ROUTER_PORT))

    while True:
        data, addr = sock.recvfrom(ROUTER_BUFFER_SIZE)
        raw_message = data.decode(errors="ignore").strip()

        if raw_message == "":
            continue

        target, actor, status = parse_message(raw_message)

        print(f"[RX] from={addr} raw={raw_message!r} -> target={target}, actor={actor}, status={status}")

        result = handle_detach_request(target, actor, status, raw_message)
        print(f"[RESULT] {result}")


if __name__ == "__main__":
    main()
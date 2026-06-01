import os
import pygame
import socket
import time
import threading
import json

# ============================================================
# keyboard.py
# Multi Raspberry Pi keyboard controller
# UDP command sender + UDP RSSI guard listener
#
# 기능:
#   1. 방향키로 로봇 주행 제어
#   2. U/D로 HEAD 고개 서보 제어
#   3. C를 누르고 있는 동안 HEAD 앞쪽 고개 유닛 DC모터 2개 회전
#   4. 키보드 숫자 1/2/3/4로 수동 순차 분리
#
# 수동 분리:
#   1 -> HEAD detach servo 작동
#        이후 NODE1은 주행 명령 대상에서 제외
#
#   2 -> NODE1 detach servo 작동
#        이후 NODE2는 주행 명령 대상에서 제외
#
#   3 -> NODE2 detach servo 작동
#        이후 NODE3는 주행 명령 대상에서 제외
#
#   4 -> NODE3 detach servo 작동
#        이후 NODE3는 주행 명령 대상에서 제외
#
#   R -> 분리 상태 초기화, 테스트용
#
# 포트:
#   UDP 5000 -> keyboard.py가 각 Pi로 제어 명령 전송
#   UDP 6000 -> keyboard.py 테스트용 guard listener
#
# AP IP 설정:
#   HEAD  = 192.168.4.1
#   NODE1 = 192.168.4.11
#   NODE2 = 192.168.4.12
#   NODE3 = 192.168.4.13
#
# 실제 자동분리:
#   실제 자동분리는 keyboard.py가 아니라 HEAD Pi의 head_detach_router.py에서 처리한다.
#   keyboard.py의 숫자 detach는 테스트용이다.
#
# 현재 기구 보정:
#   실제 전/후진이 반대로 나왔기 때문에
#     UP   -> backward 명령 전송
#     DOWN -> forward 명령 전송
#
#   실제 좌/우가 반대로 나왔기 때문에
#     LEFT  -> right 계열 명령 전송
#     RIGHT -> left 계열 명령 전송
# ============================================================


# =========================
# Unit IP / port settings
# =========================

HEAD_IP = os.environ.get("HEAD_IP", "192.168.4.1")
NODE1_IP = os.environ.get("NODE1_IP", "192.168.4.11")
NODE2_IP = os.environ.get("NODE2_IP", "192.168.4.12")
NODE3_IP = os.environ.get("NODE3_IP", "192.168.4.13")

PORT = int(os.environ.get("ROBOT_UDP_PORT", "5000"))

HEAD_NAME = "HEAD"
NODE1_NAME = "NODE1"
NODE2_NAME = "NODE2"
NODE3_NAME = "NODE3"

HEAD_UNIT = (HEAD_NAME, HEAD_IP, PORT)
NODE1_UNIT = (NODE1_NAME, NODE1_IP, PORT)
NODE2_UNIT = (NODE2_NAME, NODE2_IP, PORT)
NODE3_UNIT = (NODE3_NAME, NODE3_IP, PORT)

NODE_UNITS = [
    NODE1_UNIT,
    NODE2_UNIT,
    NODE3_UNIT,
]

ALL_UNITS = [
    HEAD_UNIT,
    NODE1_UNIT,
    NODE2_UNIT,
    NODE3_UNIT,
]


# =========================
# UDP command settings
# =========================

CONNECT_TIMEOUT = 0.2

UDP_SEND_REPEAT = 2
UDP_REPEAT_DELAY = 0.01

DRIVE_SEND_INTERVAL = 0.08
SERVO_SEND_INTERVAL = 0.08
FRONT_MOTOR_SEND_INTERVAL = 0.08


# =========================
# RSSI guard listener settings
# =========================
# 실제 자동분리는 head_detach_router.py에서 처리.
# 여기는 keyboard.py에서 테스트할 때만 사용.

GUARD_HOST = "0.0.0.0"
GUARD_PORT = int(os.environ.get("GUARD_PORT", "6000"))
GUARD_BUFFER_SIZE = 1024


# =========================
# Detached state
# =========================

detached_units = {
    HEAD_NAME: False,
    NODE1_NAME: False,
    NODE2_NAME: False,
    NODE3_NAME: False,
}

guard_event_lock = threading.Lock()
pending_guard_events = []

auto_detached_stations = set()

VALID_DETACH_TARGETS = {
    HEAD_NAME,
    NODE1_NAME,
    NODE2_NAME,
    NODE3_NAME,
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
}


# =========================
# UDP send functions
# =========================

def is_valid_ip_text(ip):
    return ip is not None and str(ip).strip() != ""


def send_command(ip, port, command):
    if not is_valid_ip_text(ip):
        print(f"[UDP SKIP] empty IP <- {command}")
        return False

    message = (command + "\n").encode()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(CONNECT_TIMEOUT)

            for _ in range(UDP_SEND_REPEAT):
                sock.sendto(message, (ip, port))
                time.sleep(UDP_REPEAT_DELAY)

        return True

    except Exception as e:
        print(f"[UDP FAIL] {ip}:{port} <- {command} / {e}")
        return False


def send_unit_command(name, ip, port, command):
    ok = send_command(ip, port, command)

    if ok:
        print(f"  [UDP OK] {name} {ip}:{port} <- {command}")
    else:
        print(f"  [UDP X]  {name} {ip}:{port} <- {command}")


def send_drive_to_unit(unit, command):
    name, ip, port = unit

    if detached_units.get(name, False):
        print(f"  [SKIP] {name} is detached. drive command ignored.")
        return

    send_unit_command(name, ip, port, command)


def send_head_drive(command):
    print(f"[HEAD DRIVE SEND] {command}")
    send_drive_to_unit(HEAD_UNIT, command)


def send_nodes_drive(command):
    print(f"[NODE DRIVE SEND] {command}")

    for unit in NODE_UNITS:
        send_drive_to_unit(unit, command)


def send_all_stop():
    print("[ALL STOP SEND]")

    for name, ip, port in ALL_UNITS:
        send_unit_command(name, ip, port, "stop")


def send_head_servo(command):
    print(f"[HEAD SERVO SEND] {command}")

    name, ip, port = HEAD_UNIT
    send_unit_command(name, ip, port, command)


def send_head_front_motor(command):
    print(f"[HEAD FRONT MOTOR SEND] {command}")

    name, ip, port = HEAD_UNIT
    send_unit_command(name, ip, port, command)


def force_stop_unit(unit):
    name, ip, port = unit
    print(f"[FORCE STOP] {name}")
    send_unit_command(name, ip, port, "stop")


# =========================
# Manual sequential detach functions
# =========================

def manual_detach_step_1():
    """
    키보드 1번:
      HEAD의 detach servo 작동
      이후 NODE1은 주행 명령 대상에서 제외
    """
    print("====================================")
    print("[DETACH 1] HEAD detach_press -> NODE1 disabled")
    print("====================================")

    name, ip, port = HEAD_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE1_NAME] = True
    force_stop_unit(NODE1_UNIT)

    auto_detached_stations.add(HEAD_NAME)

    print("[STATE] NODE1 detached. NODE1 will no longer receive drive commands.")


def manual_detach_step_2():
    """
    키보드 2번:
      NODE1의 detach servo 작동
      이후 NODE2는 주행 명령 대상에서 제외
    """
    print("====================================")
    print("[DETACH 2] NODE1 detach_press -> NODE2 disabled")
    print("====================================")

    name, ip, port = NODE1_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE2_NAME] = True
    force_stop_unit(NODE2_UNIT)

    auto_detached_stations.add(NODE1_NAME)

    print("[STATE] NODE2 detached. NODE2 will no longer receive drive commands.")


def manual_detach_step_3():
    """
    키보드 3번:
      NODE2의 detach servo 작동
      이후 NODE3는 주행 명령 대상에서 제외
    """
    print("====================================")
    print("[DETACH 3] NODE2 detach_press -> NODE3 disabled")
    print("====================================")

    name, ip, port = NODE2_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE3_NAME] = True
    force_stop_unit(NODE3_UNIT)

    auto_detached_stations.add(NODE2_NAME)

    print("[STATE] NODE3 detached. NODE3 will no longer receive drive commands.")


def manual_detach_step_4():
    """
    키보드 4번:
      NODE3의 detach servo 작동
      이후 NODE3는 주행 명령 대상에서 제외

    마지막 유닛용 예비 동작.
    Node3 뒤에 추가 노드가 없으면 NODE3 자체만 정지/비활성화한다.
    """
    print("====================================")
    print("[DETACH 4] NODE3 detach_press -> NODE3 disabled")
    print("====================================")

    name, ip, port = NODE3_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE3_NAME] = True
    force_stop_unit(NODE3_UNIT)

    auto_detached_stations.add(NODE3_NAME)

    print("[STATE] NODE3 detached. NODE3 will no longer receive drive commands.")


def send_detach_to_head():
    manual_detach_step_1()


def send_detach_to_node1():
    manual_detach_step_2()


def send_detach_to_node2():
    manual_detach_step_3()


def send_detach_to_node3():
    manual_detach_step_4()


def reset_detach_state():
    detached_units[HEAD_NAME] = False
    detached_units[NODE1_NAME] = False
    detached_units[NODE2_NAME] = False
    detached_units[NODE3_NAME] = False

    auto_detached_stations.clear()

    print("====================================")
    print("[STATE RESET] HEAD, NODE1, NODE2, NODE3 are active again.")
    print("====================================")


# =========================
# RSSI guard parsing / test auto detach
# =========================

def normalize_station_name(value):
    if value is None:
        return None

    text = str(value).strip().upper()
    text = text.replace("-", "_")
    text = text.replace(" ", "_")

    aliases = {
        "HEAD": HEAD_NAME,
        "HEAD_PI": HEAD_NAME,
        "HEADPI": HEAD_NAME,

        "NODE1": NODE1_NAME,
        "NODE1_PI": NODE1_NAME,
        "NODE1PI": NODE1_NAME,
        "NODE_1": NODE1_NAME,

        "NODE2": NODE2_NAME,
        "NODE2_PI": NODE2_NAME,
        "NODE2PI": NODE2_NAME,
        "NODE_2": NODE2_NAME,

        "NODE3": NODE3_NAME,
        "NODE3_PI": NODE3_NAME,
        "NODE3PI": NODE3_NAME,
        "NODE_3": NODE3_NAME,
    }

    return aliases.get(text)


def normalize_status(value):
    if value is None:
        return None

    text = str(value).strip().lower()
    text = text.replace("-", "_")
    text = text.replace(" ", "_")

    return text


def parse_guard_json_message(raw_message):
    try:
        data = json.loads(raw_message)
    except Exception as e:
        print(f"[GUARD PARSE FAIL] JSON error: {e}")
        return None, None

    target = (
        data.get("detach_unit")
        or data.get("detach_target")
        or data.get("target_unit")
        or data.get("target")
        or data.get("station")
        or data.get("node")
        or data.get("unit")
    )

    status = (
        data.get("guard_status")
        or data.get("status")
        or data.get("state")
        or data.get("command")
        or data.get("action")
    )

    station = normalize_station_name(target)
    guard_status = normalize_status(status)

    if station is not None and guard_status is None:
        guard_status = "detach_candidate"

    return station, guard_status


def parse_guard_text_message(raw_message):
    normalized = raw_message.strip()

    if normalized == "":
        return None, None

    upper_normalized = normalized.upper()
    upper_normalized = upper_normalized.replace("-", "_")

    direct_patterns = {
        "HEAD_DETACH": HEAD_NAME,
        "DETACH_HEAD": HEAD_NAME,
        "HEAD_DROP": HEAD_NAME,
        "DROP_HEAD": HEAD_NAME,

        "NODE1_DETACH": NODE1_NAME,
        "DETACH_NODE1": NODE1_NAME,
        "NODE1_DROP": NODE1_NAME,
        "DROP_NODE1": NODE1_NAME,

        "NODE2_DETACH": NODE2_NAME,
        "DETACH_NODE2": NODE2_NAME,
        "NODE2_DROP": NODE2_NAME,
        "DROP_NODE2": NODE2_NAME,

        "NODE3_DETACH": NODE3_NAME,
        "DETACH_NODE3": NODE3_NAME,
        "NODE3_DROP": NODE3_NAME,
        "DROP_NODE3": NODE3_NAME,
    }

    compact = upper_normalized.replace(" ", "_").replace(",", "_").replace(":", "_").replace(";", "_")

    for pattern, station in direct_patterns.items():
        if pattern in compact:
            return station, "detach_candidate"

    for delimiter in [",", ":", ";"]:
        normalized = normalized.replace(delimiter, " ")

    parts = [p.strip() for p in normalized.split() if p.strip()]

    if len(parts) == 1:
        station = normalize_station_name(parts[0])
        if station is not None:
            return station, "detach_candidate"
        return None, None

    station = None
    guard_status = None

    for part in parts:
        maybe_station = normalize_station_name(part)
        if maybe_station is not None:
            station = maybe_station
            break

    for part in parts:
        maybe_status = normalize_status(part)
        if maybe_status in DETACH_STATUS_WORDS:
            guard_status = maybe_status
            break

    if station is not None and guard_status is None:
        guard_status = "detach_candidate"

    return station, guard_status


def parse_guard_message(raw_message):
    """
    keyboard.py 테스트용 guard 메시지 파싱.

    실제 자동분리는:
      통신부 -> HEAD Pi의 head_detach_router.py -> actor 유닛 control server
    흐름으로 처리한다.
    """
    raw_message = raw_message.strip()

    if raw_message == "":
        return None, None

    if raw_message.startswith("{"):
        return parse_guard_json_message(raw_message)

    return parse_guard_text_message(raw_message)


def handle_auto_detach_candidate(station):
    """
    keyboard.py 내부 테스트용 자동분리 정책.

    실제 자동분리는 head_detach_router.py에서 처리한다.
    여기서는 노트북에서 테스트할 때만 사용한다.
    """
    station = normalize_station_name(station)

    if station is None:
        print("[AUTO DETACH TEST] station is None or unsupported")
        return "unknown_station"

    if station in auto_detached_stations:
        print(f"[AUTO DETACH TEST] {station} already processed. ignored.")
        return "already_processed"

    print("====================================")
    print(f"[AUTO DETACH TEST] detach command target={station}")
    print("====================================")

    if station == HEAD_NAME:
        manual_detach_step_1()
        return "HEAD detach -> NODE1 disabled"

    if station == NODE1_NAME:
        manual_detach_step_2()
        return "NODE1 detach -> NODE2 disabled"

    if station == NODE2_NAME:
        manual_detach_step_3()
        return "NODE2 detach -> NODE3 disabled"

    if station == NODE3_NAME:
        manual_detach_step_4()
        return "NODE3 detach -> NODE3 disabled"

    print(f"[AUTO DETACH TEST] Unsupported station: {station}")
    return "unsupported_station"


def guard_listener_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((GUARD_HOST, GUARD_PORT))

    print("====================================")
    print(f"[GUARD TEST] UDP listener started on {GUARD_HOST}:{GUARD_PORT}")
    print("This listener is for keyboard-side testing only.")
    print("Real auto-detach should go to head_detach_router.py on HEAD Pi.")
    print("Guard message examples:")
    print("  HEAD,detach_candidate")
    print("  NODE1,detach_candidate")
    print("  NODE2,detach_candidate")
    print("  NODE3,detach_candidate")
    print("  NODE1 detach")
    print("  detach NODE1")
    print("  node1_detach")
    print('  {"station":"NODE1","guard_status":"detach_candidate"}')
    print('  {"detach_unit":"NODE1"}')
    print("====================================")

    while True:
        try:
            data, addr = sock.recvfrom(GUARD_BUFFER_SIZE)
            raw_message = data.decode(errors="ignore").strip()

            station, guard_status = parse_guard_message(raw_message)

            if station is None or guard_status is None:
                print(f"[GUARD TEST] Invalid message from {addr}: {raw_message}")
                continue

            print(f"[GUARD TEST] from {addr}: station={station}, status={guard_status}")

            with guard_event_lock:
                pending_guard_events.append((station, guard_status))

        except Exception as e:
            print(f"[GUARD TEST] listener error: {e}")
            time.sleep(0.1)


def process_pending_guard_events():
    with guard_event_lock:
        guard_events = list(pending_guard_events)
        pending_guard_events.clear()

    results = []

    for station, guard_status in guard_events:
        guard_status = normalize_status(guard_status)

        if guard_status in DETACH_STATUS_WORDS:
            result = handle_auto_detach_candidate(station)
            results.append(f"AUTO TEST {station}: {result}")

        elif guard_status == "recovered":
            print(f"[GUARD TEST] {station} recovered. no detach action.")
            results.append(f"{station}: recovered")

        elif guard_status == "watching":
            print(f"[GUARD TEST] {station} watching. no detach action.")
            results.append(f"{station}: watching")

        elif guard_status == "link_ok":
            print(f"[GUARD TEST] {station} link_ok. no detach action.")
            results.append(f"{station}: link_ok")

        else:
            print(f"[GUARD TEST] {station} unsupported status: {guard_status}")
            results.append(f"{station}: unsupported {guard_status}")

    return results


# =========================
# Key interpretation
# =========================

def get_drive_commands_from_keys(keys):
    """
    반환:
      head_command, node_command

    의도:
      UP/DOWN:
        전체 활성 유닛 이동

      UP/DOWN + LEFT/RIGHT:
        HEAD는 약한 조향주행
        NODE들은 천천히 직진/후진

      LEFT/RIGHT only:
        HEAD만 강한 조향
        NODE들은 정지
    """
    up = keys[pygame.K_UP]
    down = keys[pygame.K_DOWN]
    left = keys[pygame.K_LEFT]
    right = keys[pygame.K_RIGHT]

    if up and left:
        return "mild_backward_right", "slow_backward"

    if up and right:
        return "mild_backward_left", "slow_backward"

    if down and left:
        return "mild_forward_right", "slow_forward"

    if down and right:
        return "mild_forward_left", "slow_forward"

    if up:
        return "backward", "backward"

    if down:
        return "forward", "forward"

    if left:
        return "right", "stop"

    if right:
        return "left", "stop"

    return "stop", "stop"


def get_head_servo_command_from_keys(keys):
    head_up = keys[pygame.K_u]
    head_down = keys[pygame.K_d]

    if head_up and not head_down:
        return "head_up_step"

    if head_down and not head_up:
        return "head_down_step"

    return None


def get_front_motor_command_from_keys(keys):
    if keys[pygame.K_c]:
        return "front_motor_forward"

    return "front_motor_stop"


# =========================
# UI drawing
# =========================

def draw_text(screen, font, text, x, y):
    rendered = font.render(text, True, (0, 0, 0))
    screen.blit(rendered, (x, y))


def draw_screen(
    screen,
    font_title,
    font_text,
    head_drive_command,
    node_drive_command,
    head_servo_command,
    front_motor_command,
    last_detach_command,
):
    screen.fill((245, 245, 245))

    draw_text(screen, font_title, "Multi Unit Robot UDP Control", 30, 25)

    draw_text(screen, font_text, f"HEAD drive command: {head_drive_command}", 30, 75)
    draw_text(screen, font_text, f"NODE drive command: {node_drive_command}", 30, 105)

    if head_servo_command is None:
        servo_text = "none"
    else:
        servo_text = head_servo_command

    draw_text(screen, font_text, f"HEAD servo command: {servo_text}", 30, 135)
    draw_text(screen, font_text, f"Front motor command: {front_motor_command}", 30, 165)
    draw_text(screen, font_text, f"Last detach/guard: {last_detach_command}", 30, 195)

    draw_text(screen, font_text, "Detached state:", 30, 235)
    draw_text(screen, font_text, f"HEAD detached: {detached_units[HEAD_NAME]}", 45, 265)
    draw_text(screen, font_text, f"NODE1 detached: {detached_units[NODE1_NAME]}", 45, 295)
    draw_text(screen, font_text, f"NODE2 detached: {detached_units[NODE2_NAME]}", 45, 325)
    draw_text(screen, font_text, f"NODE3 detached: {detached_units[NODE3_NAME]}", 45, 355)

    draw_text(screen, font_text, "Drive keys:", 30, 405)
    draw_text(screen, font_text, "UP: actual forward, all active units", 45, 435)
    draw_text(screen, font_text, "DOWN: actual backward, all active units", 45, 465)
    draw_text(screen, font_text, "UP + LEFT/RIGHT: HEAD mild turn, NODE slow forward", 45, 495)
    draw_text(screen, font_text, "DOWN + LEFT/RIGHT: HEAD mild turn, NODE slow backward", 45, 525)
    draw_text(screen, font_text, "LEFT / RIGHT only: HEAD strong steering, NODE stop", 45, 555)

    draw_text(screen, font_text, "Head unit keys:", 30, 605)
    draw_text(screen, font_text, "Hold U: head goes up", 45, 635)
    draw_text(screen, font_text, "Hold D: head goes down", 45, 665)
    draw_text(screen, font_text, "Hold C: front head-unit DC motors rotate", 45, 695)

    draw_text(screen, font_text, "Manual sequential detach:", 30, 745)
    draw_text(screen, font_text, "1: HEAD detach -> NODE1 disabled", 45, 775)
    draw_text(screen, font_text, "2: NODE1 detach -> NODE2 disabled", 45, 805)
    draw_text(screen, font_text, "3: NODE2 detach -> NODE3 disabled", 45, 835)
    draw_text(screen, font_text, "4: NODE3 detach -> NODE3 disabled", 45, 865)
    draw_text(screen, font_text, "R: reset detached state", 45, 895)

    draw_text(screen, font_text, f"Guard test listener: {GUARD_HOST}:{GUARD_PORT}", 30, 925)
    draw_text(screen, font_text, "ESC: quit", 30, 950)

    pygame.display.flip()


# =========================
# Main
# =========================

def main():
    guard_thread = threading.Thread(target=guard_listener_loop)
    guard_thread.daemon = True
    guard_thread.start()

    pygame.init()

    screen = pygame.display.set_mode((1080, 990))
    pygame.display.set_caption("Multi Raspberry Pi Robot UDP Keyboard Control")

    font_title = pygame.font.SysFont(None, 36)
    font_text = pygame.font.SysFont(None, 25)

    clock = pygame.time.Clock()

    running = True

    last_head_drive_command = None
    last_node_drive_command = None

    last_head_drive_send_time = 0.0
    last_node_drive_send_time = 0.0

    last_head_servo_send_time = 0.0
    current_head_servo_command = None

    last_front_motor_command = None
    last_front_motor_send_time = 0.0
    current_front_motor_command = "front_motor_stop"

    last_detach_command = "none"

    print("====================================")
    print(" Multi Unit Robot UDP Keyboard Control")
    print("====================================")
    print("IP:")
    print(f"  HEAD_IP  = {HEAD_IP}")
    print(f"  NODE1_IP = {NODE1_IP}")
    print(f"  NODE2_IP = {NODE2_IP}")
    print(f"  NODE3_IP = {NODE3_IP}")
    print(f"  PORT     = {PORT}")
    print("------------------------------------")
    print("Drive:")
    print("  UP              : actual forward")
    print("  DOWN            : actual backward")
    print("  UP + LEFT       : HEAD mild steering, NODE slow forward")
    print("  UP + RIGHT      : HEAD mild steering, NODE slow forward")
    print("  DOWN + LEFT     : HEAD mild backward steering, NODE slow backward")
    print("  DOWN + RIGHT    : HEAD mild backward steering, NODE slow backward")
    print("  LEFT only       : HEAD strong steering, NODE stop")
    print("  RIGHT only      : HEAD strong steering, NODE stop")
    print("------------------------------------")
    print("Head unit:")
    print("  Hold U : head goes up")
    print("  Hold D : head goes down")
    print("  Hold C : front head-unit DC motors rotate")
    print("------------------------------------")
    print("Manual sequential detach:")
    print("  1 : HEAD detach, then NODE1 disabled")
    print("  2 : NODE1 detach, then NODE2 disabled")
    print("  3 : NODE2 detach, then NODE3 disabled")
    print("  4 : NODE3 detach, then NODE3 disabled")
    print("  R : reset detached state")
    print("------------------------------------")
    print("Auto detach:")
    print("  Real auto-detach should be handled by head_detach_router.py on HEAD Pi.")
    print("  keyboard.py guard listener is for testing only.")
    print("------------------------------------")
    print("ESC / close       : quit")
    print("IMPORTANT         : Click pygame window first")
    print("====================================")

    send_all_stop()
    send_head_front_motor("front_motor_stop")

    last_head_drive_command = "stop"
    last_node_drive_command = "stop"
    last_front_motor_command = "front_motor_stop"

    last_head_drive_send_time = time.time()
    last_node_drive_send_time = time.time()
    last_front_motor_send_time = time.time()

    try:
        while running:
            now = time.time()

            guard_results = process_pending_guard_events()
            if guard_results:
                last_detach_command = guard_results[-1]

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    send_head_front_motor("front_motor_stop")
                    send_all_stop()
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        send_head_front_motor("front_motor_stop")
                        send_all_stop()
                        running = False

                    elif event.key == pygame.K_1:
                        manual_detach_step_1()
                        last_detach_command = "MANUAL 1: HEAD detach -> NODE1 disabled"

                    elif event.key == pygame.K_2:
                        manual_detach_step_2()
                        last_detach_command = "MANUAL 2: NODE1 detach -> NODE2 disabled"

                    elif event.key == pygame.K_3:
                        manual_detach_step_3()
                        last_detach_command = "MANUAL 3: NODE2 detach -> NODE3 disabled"

                    elif event.key == pygame.K_4:
                        manual_detach_step_4()
                        last_detach_command = "MANUAL 4: NODE3 detach -> NODE3 disabled"

                    elif event.key == pygame.K_r:
                        reset_detach_state()
                        last_detach_command = "detach state reset"

            keys = pygame.key.get_pressed()

            head_drive_command, node_drive_command = get_drive_commands_from_keys(keys)

            if head_drive_command != last_head_drive_command:
                send_head_drive(head_drive_command)
                last_head_drive_command = head_drive_command
                last_head_drive_send_time = now

            elif head_drive_command != "stop" and now - last_head_drive_send_time >= DRIVE_SEND_INTERVAL:
                send_head_drive(head_drive_command)
                last_head_drive_send_time = now

            if node_drive_command != last_node_drive_command:
                send_nodes_drive(node_drive_command)
                last_node_drive_command = node_drive_command
                last_node_drive_send_time = now

            elif node_drive_command != "stop" and now - last_node_drive_send_time >= DRIVE_SEND_INTERVAL:
                send_nodes_drive(node_drive_command)
                last_node_drive_send_time = now

            current_head_servo_command = get_head_servo_command_from_keys(keys)

            if current_head_servo_command is not None:
                if now - last_head_servo_send_time >= SERVO_SEND_INTERVAL:
                    send_head_servo(current_head_servo_command)
                    last_head_servo_send_time = now

            current_front_motor_command = get_front_motor_command_from_keys(keys)

            if current_front_motor_command != last_front_motor_command:
                send_head_front_motor(current_front_motor_command)
                last_front_motor_command = current_front_motor_command
                last_front_motor_send_time = now

            elif (
                current_front_motor_command != "front_motor_stop"
                and now - last_front_motor_send_time >= FRONT_MOTOR_SEND_INTERVAL
            ):
                send_head_front_motor(current_front_motor_command)
                last_front_motor_send_time = now

            draw_screen(
                screen,
                font_title,
                font_text,
                head_drive_command,
                node_drive_command,
                current_head_servo_command,
                current_front_motor_command,
                last_detach_command,
            )

            clock.tick(60)

    finally:
        send_head_front_motor("front_motor_stop")
        send_all_stop()
        pygame.quit()
        print("Keyboard control stopped.")


if __name__ == "__main__":
    main()
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
#   3. RSSI guard 신호 detach_candidate 수신 시 자동 분리
#   4. 키보드 숫자 1/2/3으로 수동 순차 분리
#
# 수동 분리:
#   1 -> HEAD detach servo 작동
#        이후 NODE1은 주행 명령 대상에서 제외
#
#   2 -> NODE1 detach servo 작동
#        이후 NODE2는 주행 명령 대상에서 제외
#
#   3 -> NODE2 detach servo 작동
#        이후 NODE2는 주행 명령 대상에서 제외
#
#   R -> 분리 상태 초기화, 테스트용
#
# 자동 분리:
#   통신부에서 UDP 6000번 포트로 아래 메시지 수신 시 자동 분리
#     NODE1,detach_candidate
#     NODE2,detach_candidate
#     {"station":"NODE1","guard_status":"detach_candidate"}
#
# 포트:
#   UDP 5000 -> keyboard.py가 각 Pi로 제어 명령 전송
#   UDP 6000 -> 통신부가 keyboard.py로 RSSI guard 상태 전송
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

HEAD_IP = "10.180.86.171"
NODE1_IP = "192.168.50.252"
NODE2_IP = "192.168.50.179"

PORT = 5000

HEAD_NAME = "HEAD"
NODE1_NAME = "NODE1"
NODE2_NAME = "NODE2"

HEAD_UNIT = (HEAD_NAME, HEAD_IP, PORT)
NODE1_UNIT = (NODE1_NAME, NODE1_IP, PORT)
NODE2_UNIT = (NODE2_NAME, NODE2_IP, PORT)

NODE_UNITS = [
    NODE1_UNIT,
    NODE2_UNIT,
]

ALL_UNITS = [
    HEAD_UNIT,
    NODE1_UNIT,
    NODE2_UNIT,
]


# =========================
# UDP command settings
# =========================

CONNECT_TIMEOUT = 0.2

UDP_SEND_REPEAT = 2
UDP_REPEAT_DELAY = 0.01

DRIVE_SEND_INTERVAL = 0.08
SERVO_SEND_INTERVAL = 0.08


# =========================
# RSSI guard listener settings
# =========================

GUARD_HOST = "0.0.0.0"
GUARD_PORT = 6000
GUARD_BUFFER_SIZE = 1024


# =========================
# Detached state
# =========================

detached_units = {
    HEAD_NAME: False,
    NODE1_NAME: False,
    NODE2_NAME: False,
}

guard_event_lock = threading.Lock()
pending_guard_events = []

auto_detached_stations = set()

# 자동 분리 매핑
# NODE1 링크가 약해짐 -> HEAD 분리기 작동 -> NODE1 비활성화
# NODE2 링크가 약해짐 -> NODE1 분리기 작동 -> NODE2 비활성화
AUTO_DETACH_ACTION_BY_STATION = {
    "HEAD": "head",
    "HEAD_PI": "head",
    "HEAD-PI": "head",

    "NODE1": "head",
    "NODE1_PI": "head",
    "NODE1-PI": "head",

    "NODE2": "node1",
    "NODE2_PI": "node1",
    "NODE2-PI": "node1",
}


# =========================
# UDP send functions
# =========================

def send_command(ip, port, command):
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
    print("[MANUAL DETACH 1] HEAD detach_press")
    print("====================================")

    name, ip, port = HEAD_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE1_NAME] = True
    force_stop_unit(NODE1_UNIT)

    print("[STATE] NODE1 detached. NODE1 will no longer receive drive commands.")


def manual_detach_step_2():
    """
    키보드 2번:
      NODE1의 detach servo 작동
      이후 NODE2는 주행 명령 대상에서 제외
    """
    print("====================================")
    print("[MANUAL DETACH 2] NODE1 detach_press")
    print("====================================")

    name, ip, port = NODE1_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE2_NAME] = True
    force_stop_unit(NODE2_UNIT)

    print("[STATE] NODE2 detached. NODE2 will no longer receive drive commands.")


def manual_detach_step_3():
    """
    키보드 3번:
      NODE2의 detach servo 작동
      이후 NODE2는 주행 명령 대상에서 제외
    """
    print("====================================")
    print("[MANUAL DETACH 3] NODE2 detach_press")
    print("====================================")

    name, ip, port = NODE2_UNIT
    send_unit_command(name, ip, port, "detach_press")

    detached_units[NODE2_NAME] = True
    force_stop_unit(NODE2_UNIT)

    print("[STATE] NODE2 detached. NODE2 will no longer receive drive commands.")


# 기존 자동 분리 함수 이름 유지용 alias
def send_detach_to_head():
    manual_detach_step_1()


def send_detach_to_node1():
    manual_detach_step_2()


def send_detach_to_node2():
    manual_detach_step_3()


def reset_detach_state():
    detached_units[HEAD_NAME] = False
    detached_units[NODE1_NAME] = False
    detached_units[NODE2_NAME] = False

    auto_detached_stations.clear()

    print("====================================")
    print("[STATE RESET] HEAD, NODE1, NODE2 are active again.")
    print("====================================")


# =========================
# RSSI guard parsing / auto detach
# =========================

def parse_guard_message(raw_message):
    """
    지원 형식:
      NODE1,detach_candidate
      NODE1 detach_candidate
      {"station":"NODE1","guard_status":"detach_candidate"}

    반환:
      station, guard_status
    """
    raw_message = raw_message.strip()

    if raw_message == "":
        return None, None

    if raw_message.startswith("{"):
        try:
            data = json.loads(raw_message)

            station = (
                data.get("station")
                or data.get("node")
                or data.get("unit")
                or data.get("target")
            )

            guard_status = (
                data.get("guard_status")
                or data.get("status")
                or data.get("state")
            )

            if station is None or guard_status is None:
                return None, None

            return str(station).upper(), str(guard_status).lower()

        except Exception as e:
            print(f"[GUARD PARSE FAIL] JSON error: {e}")
            return None, None

    if "," in raw_message:
        parts = [p.strip() for p in raw_message.split(",")]
    else:
        parts = raw_message.split()

    if len(parts) < 2:
        return None, None

    station = parts[0].upper()
    guard_status = parts[1].lower()

    return station, guard_status


def handle_auto_detach_candidate(station):
    """
    자동 분리 정책:
      NODE1 detach_candidate -> HEAD detach -> NODE1 disabled
      NODE2 detach_candidate -> NODE1 detach -> NODE2 disabled
    """
    station = station.upper()

    if station in auto_detached_stations:
        print(f"[AUTO DETACH] {station} already processed. ignored.")
        return "already_processed"

    action = AUTO_DETACH_ACTION_BY_STATION.get(station)

    if action is None:
        print(f"[AUTO DETACH] Unknown station: {station}")
        return "unknown_station"

    print("====================================")
    print(f"[AUTO DETACH] station={station}, action={action}")
    print("====================================")

    if action == "head":
        manual_detach_step_1()
        auto_detached_stations.add(station)
        return "HEAD detach -> NODE1 disabled"

    if action == "node1":
        manual_detach_step_2()
        auto_detached_stations.add(station)
        return "NODE1 detach -> NODE2 disabled"

    if action == "node2":
        manual_detach_step_3()
        auto_detached_stations.add(station)
        return "NODE2 detach -> NODE2 disabled"

    print(f"[AUTO DETACH] Unsupported action: {action}")
    return "unsupported_action"


def guard_listener_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((GUARD_HOST, GUARD_PORT))

    print("====================================")
    print(f"[GUARD] UDP listener started on {GUARD_HOST}:{GUARD_PORT}")
    print("Guard message examples:")
    print("  NODE1,detach_candidate")
    print("  NODE2,detach_candidate")
    print('  {"station":"NODE1","guard_status":"detach_candidate"}')
    print("====================================")

    while True:
        try:
            data, addr = sock.recvfrom(GUARD_BUFFER_SIZE)
            raw_message = data.decode(errors="ignore").strip()

            station, guard_status = parse_guard_message(raw_message)

            if station is None or guard_status is None:
                print(f"[GUARD] Invalid message from {addr}: {raw_message}")
                continue

            print(f"[GUARD] from {addr}: station={station}, status={guard_status}")

            with guard_event_lock:
                pending_guard_events.append((station, guard_status))

        except Exception as e:
            print(f"[GUARD] listener error: {e}")
            time.sleep(0.1)


def process_pending_guard_events():
    with guard_event_lock:
        guard_events = list(pending_guard_events)
        pending_guard_events.clear()

    results = []

    for station, guard_status in guard_events:
        if guard_status == "detach_candidate":
            result = handle_auto_detach_candidate(station)
            results.append(f"AUTO {station}: {result}")

        elif guard_status == "recovered":
            print(f"[GUARD] {station} recovered. no detach action.")
            results.append(f"{station}: recovered")

        elif guard_status == "watching":
            print(f"[GUARD] {station} watching. no detach action.")
            results.append(f"{station}: watching")

        else:
            print(f"[GUARD] {station} unsupported status: {guard_status}")
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

    # 실제 전진 + 조향
    # 실제 전진이 backward 계열이라 backward 명령 사용
    # 실제 좌우가 반대라 LEFT 입력은 right 계열 사용
    if up and left:
        return "mild_backward_right", "slow_backward"

    if up and right:
        return "mild_backward_left", "slow_backward"

    # 실제 후진 + 조향
    # 실제 후진이 forward 계열이라 forward 명령 사용
    if down and left:
        return "mild_forward_right", "slow_forward"

    if down and right:
        return "mild_forward_left", "slow_forward"

    # 실제 전진 / 후진
    if up:
        return "backward", "backward"

    if down:
        return "forward", "forward"

    # 강한 단독 조향
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
    last_detach_command
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
    draw_text(screen, font_text, f"Last detach/guard: {last_detach_command}", 30, 165)

    draw_text(screen, font_text, "Detached state:", 30, 205)
    draw_text(screen, font_text, f"HEAD detached: {detached_units[HEAD_NAME]}", 45, 235)
    draw_text(screen, font_text, f"NODE1 detached: {detached_units[NODE1_NAME]}", 45, 265)
    draw_text(screen, font_text, f"NODE2 detached: {detached_units[NODE2_NAME]}", 45, 295)

    draw_text(screen, font_text, "Drive keys:", 30, 345)
    draw_text(screen, font_text, "UP: actual forward, all active units", 45, 375)
    draw_text(screen, font_text, "DOWN: actual backward, all active units", 45, 405)
    draw_text(screen, font_text, "UP + LEFT/RIGHT: HEAD mild turn, NODE slow forward", 45, 435)
    draw_text(screen, font_text, "DOWN + LEFT/RIGHT: HEAD mild turn, NODE slow backward", 45, 465)
    draw_text(screen, font_text, "LEFT / RIGHT only: HEAD strong steering, NODE stop", 45, 495)

    draw_text(screen, font_text, "Head servo keys:", 30, 545)
    draw_text(screen, font_text, "Hold U: head goes up", 45, 575)
    draw_text(screen, font_text, "Hold D: head goes down", 45, 605)

    draw_text(screen, font_text, "Manual sequential detach:", 30, 655)
    draw_text(screen, font_text, "1: HEAD detach -> NODE1 disabled", 45, 685)
    draw_text(screen, font_text, "2: NODE1 detach -> NODE2 disabled", 45, 715)
    draw_text(screen, font_text, "3: NODE2 detach -> NODE2 disabled", 45, 745)
    draw_text(screen, font_text, "R: reset detached state", 45, 775)

    draw_text(screen, font_text, f"Guard UDP listener: {GUARD_HOST}:{GUARD_PORT}", 30, 825)
    draw_text(screen, font_text, "ESC: quit", 30, 850)

    pygame.display.flip()


# =========================
# Main
# =========================

def main():
    guard_thread = threading.Thread(target=guard_listener_loop)
    guard_thread.daemon = True
    guard_thread.start()

    pygame.init()

    screen = pygame.display.set_mode((1020, 900))
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

    last_detach_command = "none"

    print("====================================")
    print(" Multi Unit Robot UDP Keyboard Control")
    print("====================================")
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
    print("Manual sequential detach:")
    print("  1 : HEAD detach, then NODE1 disabled")
    print("  2 : NODE1 detach, then NODE2 disabled")
    print("  3 : NODE2 detach, then NODE2 disabled")
    print("  R : reset detached state")
    print("------------------------------------")
    print("Auto detach:")
    print(f"  Listening guard status on UDP {GUARD_HOST}:{GUARD_PORT}")
    print("  NODE1,detach_candidate -> HEAD detach -> NODE1 disabled")
    print("  NODE2,detach_candidate -> NODE1 detach -> NODE2 disabled")
    print("------------------------------------")
    print("ESC / close       : quit")
    print("IMPORTANT         : Click pygame window first")
    print("====================================")

    send_all_stop()

    last_head_drive_command = "stop"
    last_node_drive_command = "stop"

    last_head_drive_send_time = time.time()
    last_node_drive_send_time = time.time()

    try:
        while running:
            now = time.time()

            guard_results = process_pending_guard_events()
            if guard_results:
                last_detach_command = guard_results[-1]

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    send_all_stop()
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
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
                        last_detach_command = "MANUAL 3: NODE2 detach -> NODE2 disabled"

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

            draw_screen(
                screen,
                font_title,
                font_text,
                head_drive_command,
                node_drive_command,
                current_head_servo_command,
                last_detach_command
            )

            clock.tick(60)

    finally:
        send_all_stop()
        pygame.quit()
        print("Keyboard control stopped.")


if __name__ == "__main__":
    main()
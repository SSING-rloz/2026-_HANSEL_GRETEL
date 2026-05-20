import pygame
import socket
import time

# ============================================================
# keyboard.py
# 노트북 Ubuntu용 다중 Raspberry Pi 키보드 제어 코드
#
# 주행:
#   방향키로 HEAD / NODE1 / NODE2 전체에 명령 전송
#
# 서보:
#   U를 누르고 있으면 servo_up_step을 HEAD에 반복 전송
#   D를 누르고 있으면 servo_down_step을 HEAD에 반복 전송
#   U/D를 떼면 더 이상 서보 명령을 보내지 않으므로 현재 각도에서 멈춤
#
# 좌우 회전 반전 문제 대응:
#   실제 로봇이 방향키와 반대로 회전하는 문제가 있었으므로,
#   키보드 입력에서 좌/우 명령을 반대로 매핑함.
# ============================================================


# =========================
# IP 설정
# =========================
# 반드시 실제 IP로 수정해서 사용

HEAD_IP = "192.168.50.218"
HEAD_PORT = 5000

UNITS = [
    ("HEAD", "192.168.50.218", 5000),
    ("NODE1", "192.168.50.252", 5000),
    # ("NODE2", "192.168.50.xxx", 5000),
]


# =========================
# 통신 설정
# =========================

CONNECT_TIMEOUT = 0.2

# 주행 명령 반복 전송 주기
DRIVE_SEND_INTERVAL = 0.08

# 서보 명령 반복 전송 주기
# 값이 작을수록 U/D 누를 때 고개가 빠르게 움직임
SERVO_SEND_INTERVAL = 0.08


# =========================
# 명령 전송 함수
# =========================

def send_command(ip, port, command):
    """
    특정 Raspberry Pi 하나에 TCP 명령 전송
    """
    try:
        with socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT) as sock:
            sock.sendall((command + "\n").encode())
        return True

    except Exception as e:
        print(f"[FAIL] {ip}:{port} <- {command} / {e}")
        return False


def broadcast_drive(command):
    """
    주행 명령을 모든 유닛에 전송
    """
    print(f"[DRIVE SEND] {command}")

    for name, ip, port in UNITS:
        ok = send_command(ip, port, command)

        if ok:
            print(f"  [OK] {name} {ip}:{port}")
        else:
            print(f"  [X]  {name} {ip}:{port}")


def send_head_servo(command):
    """
    서보 명령은 헤드 유닛에만 전송
    """
    print(f"[SERVO SEND] {command}")

    ok = send_command(HEAD_IP, HEAD_PORT, command)

    if ok:
        print(f"  [OK] HEAD {HEAD_IP}:{HEAD_PORT}")
    else:
        print(f"  [X]  HEAD {HEAD_IP}:{HEAD_PORT}")


# =========================
# 방향키 입력 해석
# =========================

def get_drive_command_from_keys(keys):
    """
    현재 눌린 방향키 상태를 보고 주행 명령 문자열 반환

    좌우 반전 대응:
      실제 로봇이 좌우 반대로 회전했기 때문에,
      left 입력에는 right 계열 명령을 보내고,
      right 입력에는 left 계열 명령을 보냄.
    """
    up = keys[pygame.K_UP]
    down = keys[pygame.K_DOWN]
    left = keys[pygame.K_LEFT]
    right = keys[pygame.K_RIGHT]

    if up and left:
        return "forward_right"

    if up and right:
        return "forward_left"

    if down and left:
        return "backward_right"

    if down and right:
        return "backward_left"

    if up:
        return "forward"

    if down:
        return "backward"

    if left:
        return "right"

    if right:
        return "left"

    return "stop"


def get_servo_command_from_keys(keys):
    """
    U/D 키 상태를 보고 서보 명령 반환

    U 누르는 중:
      servo_up_step

    D 누르는 중:
      servo_down_step

    둘 다 안 누름:
      None

    U와 D를 동시에 누르면 안전하게 None 처리
    """
    up_servo = keys[pygame.K_u]
    down_servo = keys[pygame.K_d]

    if up_servo and not down_servo:
        return "servo_up_step"

    if down_servo and not up_servo:
        return "servo_down_step"

    return None


# =========================
# 화면 표시 함수
# =========================

def draw_text(screen, font, text, x, y):
    rendered = font.render(text, True, (0, 0, 0))
    screen.blit(rendered, (x, y))


def draw_screen(screen, font_title, font_text, drive_command, servo_command):
    screen.fill((245, 245, 245))

    draw_text(screen, font_title, "Multi Unit Robot Control", 30, 25)

    draw_text(screen, font_text, f"Current drive command: {drive_command}", 30, 75)

    if servo_command is None:
        servo_text = "none"
    else:
        servo_text = servo_command

    draw_text(screen, font_text, f"Current servo command: {servo_text}", 30, 105)

    draw_text(screen, font_text, "Drive keys:", 30, 150)
    draw_text(screen, font_text, "UP: forward", 45, 180)
    draw_text(screen, font_text, "DOWN: backward", 45, 210)
    draw_text(screen, font_text, "UP + LEFT: forward left turn", 45, 240)
    draw_text(screen, font_text, "UP + RIGHT: forward right turn", 45, 270)
    draw_text(screen, font_text, "DOWN + LEFT: backward left turn", 45, 300)
    draw_text(screen, font_text, "DOWN + RIGHT: backward right turn", 45, 330)
    draw_text(screen, font_text, "LEFT / RIGHT only: spin", 45, 360)

    draw_text(screen, font_text, "Servo keys:", 30, 410)
    draw_text(screen, font_text, "Hold U: head goes up", 45, 440)
    draw_text(screen, font_text, "Hold D: head goes down", 45, 470)
    draw_text(screen, font_text, "Release U/D: servo stops at current angle", 45, 500)

    draw_text(screen, font_text, "Release drive keys: stop / ESC: quit", 30, 550)

    y = 590
    draw_text(screen, font_text, "Target drive units:", 30, y)
    y += 30

    for name, ip, port in UNITS:
        draw_text(screen, font_text, f"- {name}: {ip}:{port}", 45, y)
        y += 25

    pygame.display.flip()


# =========================
# 메인 함수
# =========================

def main():
    pygame.init()

    screen = pygame.display.set_mode((780, 720))
    pygame.display.set_caption("Multi Raspberry Pi Robot Keyboard Control")

    font_title = pygame.font.SysFont(None, 36)
    font_text = pygame.font.SysFont(None, 25)

    clock = pygame.time.Clock()

    running = True

    last_drive_command = None
    last_drive_send_time = 0.0

    last_servo_send_time = 0.0
    current_servo_command = None

    print("====================================")
    print(" Multi Unit Robot Keyboard Control")
    print("====================================")
    print("Drive:")
    print("  UP              : forward")
    print("  DOWN            : backward")
    print("  UP + LEFT       : forward left turn")
    print("  UP + RIGHT      : forward right turn")
    print("  DOWN + LEFT     : backward left turn")
    print("  DOWN + RIGHT    : backward right turn")
    print("  LEFT only       : left spin")
    print("  RIGHT only      : right spin")
    print("  Release         : stop")
    print("------------------------------------")
    print("Servo:")
    print("  Hold U : head goes up")
    print("  Hold D : head goes down")
    print("  Release U/D : servo stops at current angle")
    print("------------------------------------")
    print("ESC / close       : quit")
    print("IMPORTANT         : Click pygame window first")
    print("====================================")
    print("Drive target units:")

    for name, ip, port in UNITS:
        print(f"  - {name}: {ip}:{port}")

    print("Servo target:")
    print(f"  - HEAD: {HEAD_IP}:{HEAD_PORT}")
    print("====================================")

    broadcast_drive("stop")
    last_drive_command = "stop"
    last_drive_send_time = time.time()

    try:
        while running:
            now = time.time()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    broadcast_drive("stop")
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        broadcast_drive("stop")
                        running = False

            keys = pygame.key.get_pressed()

            # -------------------------
            # 주행 명령 처리
            # -------------------------
            drive_command = get_drive_command_from_keys(keys)

            if drive_command != last_drive_command:
                broadcast_drive(drive_command)
                last_drive_command = drive_command
                last_drive_send_time = now

            elif drive_command != "stop" and now - last_drive_send_time >= DRIVE_SEND_INTERVAL:
                broadcast_drive(drive_command)
                last_drive_send_time = now

            # -------------------------
            # 서보 명령 처리
            # -------------------------
            current_servo_command = get_servo_command_from_keys(keys)

            if current_servo_command is not None:
                if now - last_servo_send_time >= SERVO_SEND_INTERVAL:
                    send_head_servo(current_servo_command)
                    last_servo_send_time = now

            draw_screen(screen, font_title, font_text, drive_command, current_servo_command)
            clock.tick(60)

    finally:
        broadcast_drive("stop")
        pygame.quit()
        print("Keyboard control stopped.")


if __name__ == "__main__":
    main()

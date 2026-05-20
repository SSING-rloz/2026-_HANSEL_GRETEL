import socket
import time
import threading
import RPi.GPIO as GPIO

# ============================================================
# Head_control.py
# L298N + 엔코더 속도 피드백 제어 + 서보 제어 코드
#
# 주행 명령:
#   forward
#   backward
#   forward_left
#   forward_right
#   backward_left
#   backward_right
#   left
#   right
#   stop
#
# 서보 명령:
#   servo_up_step
#   servo_down_step
#
# 모터 드라이버:
#   L298N
#
# 모터:
#   SGM25-370 DC 12V RPM 12 엔코더 모터
#
# 엔코더 배선:
#   왼쪽 A -> GPIO5,  물리핀 29
#   왼쪽 B -> GPIO6,  물리핀 31
#   오른쪽 A -> GPIO16, 물리핀 36
#   오른쪽 B -> GPIO26, 물리핀 37
#
# 주의:
#   엔코더 출력이 5V이면 라즈베리파이 GPIO에 직접 연결 금지.
#   반드시 3.3V 출력 또는 레벨시프터 사용.
# ============================================================


UNIT_NAME = "HEAD"


# =========================
# L298N 모터 GPIO 핀
# =========================

ENA_PIN = 18
IN1_PIN = 23
IN2_PIN = 24

ENB_PIN = 13
IN3_PIN = 27
IN4_PIN = 22


# =========================
# 엔코더 GPIO 핀
# =========================

LEFT_ENC_A = 5
LEFT_ENC_B = 6

RIGHT_ENC_A = 16
RIGHT_ENC_B = 26


# =========================
# 서보 GPIO 핀
# =========================

SERVO_PIN = 12


# =========================
# 서버 설정
# =========================

HOST = "0.0.0.0"
PORT = 5000


# =========================
# PWM / PID 설정
# =========================

PWM_FREQ = 1000

CONTROL_INTERVAL = 0.05

MIN_PWM = 25
MAX_PWM = 100

# ------------------------------------------------------------
# 속도 목표값 설정
# ------------------------------------------------------------
# 단위: counts per second, CPS
#
# 이 값이 너무 낮으면 최고속도가 안 나옴.
# 이 값이 너무 높으면 PWM이 계속 100%에 붙음.
#
# 처음에는 아래 값으로 테스트하고,
# 헤드파이 터미널에 찍히는 cps 로그를 보고 조정하면 됨.
# SGM25-370 12RPM 모터는 엔코더 사양에 따라 CPS가 크게 달라질 수 있음.
# ------------------------------------------------------------

FULL_SPEED_CPS_LEFT = 800.0
FULL_SPEED_CPS_RIGHT = 800.0

TURN_INNER_RATIO = 0.45
TURN_OUTER_RATIO = 1.00
SPIN_RATIO = 0.85

# ------------------------------------------------------------
# PID 게인
# ------------------------------------------------------------
# 속도 반응이 너무 느림  -> KP 증가
# 속도가 출렁임        -> KP 감소, KD 증가
# 정상속도보다 계속 낮음 -> KI 약간 증가
# ------------------------------------------------------------

KP_LEFT = 0.035
KI_LEFT = 0.015
KD_LEFT = 0.000

KP_RIGHT = 0.035
KI_RIGHT = 0.015
KD_RIGHT = 0.000


# =========================
# 서보 설정
# =========================

SERVO_FREQ = 50

current_servo_angle = 90

SERVO_MIN_ANGLE = 40
SERVO_MAX_ANGLE = 180
SERVO_CENTER_ANGLE = 90
SERVO_STEP_ANGLE = 2

START_SERVO_CENTER_ON_BOOT = True
SERVO_HOLD = True


# =========================
# 전역 상태 변수
# =========================

running = True

left_count = 0
right_count = 0

left_last_state = 0
right_last_state = 0

encoder_lock = threading.Lock()

left_target_cps = 0.0
right_target_cps = 0.0

left_direction = "stop"
right_direction = "stop"

left_pwm_value = 0.0
right_pwm_value = 0.0

left_integral = 0.0
right_integral = 0.0

left_prev_error = 0.0
right_prev_error = 0.0

last_debug_time = 0.0
DEBUG_PRINT_INTERVAL = 0.5


# =========================
# GPIO 초기화
# =========================

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(ENA_PIN, GPIO.OUT)
GPIO.setup(IN1_PIN, GPIO.OUT)
GPIO.setup(IN2_PIN, GPIO.OUT)

GPIO.setup(ENB_PIN, GPIO.OUT)
GPIO.setup(IN3_PIN, GPIO.OUT)
GPIO.setup(IN4_PIN, GPIO.OUT)

GPIO.setup(LEFT_ENC_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LEFT_ENC_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(RIGHT_ENC_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(RIGHT_ENC_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(SERVO_PIN, GPIO.OUT)

pwm_left = GPIO.PWM(ENA_PIN, PWM_FREQ)
pwm_right = GPIO.PWM(ENB_PIN, PWM_FREQ)
servo_pwm = GPIO.PWM(SERVO_PIN, SERVO_FREQ)

pwm_left.start(0)
pwm_right.start(0)
servo_pwm.start(0)


# =========================
# 유틸 함수
# =========================

def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def clamp_pwm(value):
    return clamp(value, 0, 100)


def clamp_angle(angle):
    return int(clamp(angle, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE))


def angle_to_duty(angle):
    angle = int(clamp(angle, 0, 180))
    return 2.5 + (angle / 18.0)


# =========================
# 엔코더 콜백
# =========================

def read_encoder_state(pin_a, pin_b):
    a = GPIO.input(pin_a)
    b = GPIO.input(pin_b)
    return (a << 1) | b


def update_quadrature_count(last_state, new_state, current_count):
    transition = (last_state << 2) | new_state

    if transition in (0b0001, 0b0111, 0b1110, 0b1000):
        current_count += 1
    elif transition in (0b0010, 0b1011, 0b1101, 0b0100):
        current_count -= 1

    return current_count


def left_encoder_callback(channel):
    global left_count, left_last_state

    with encoder_lock:
        new_state = read_encoder_state(LEFT_ENC_A, LEFT_ENC_B)
        left_count = update_quadrature_count(left_last_state, new_state, left_count)
        left_last_state = new_state


def right_encoder_callback(channel):
    global right_count, right_last_state

    with encoder_lock:
        new_state = read_encoder_state(RIGHT_ENC_A, RIGHT_ENC_B)
        right_count = update_quadrature_count(right_last_state, new_state, right_count)
        right_last_state = new_state


left_last_state = read_encoder_state(LEFT_ENC_A, LEFT_ENC_B)
right_last_state = read_encoder_state(RIGHT_ENC_A, RIGHT_ENC_B)

GPIO.add_event_detect(LEFT_ENC_A, GPIO.BOTH, callback=left_encoder_callback)
GPIO.add_event_detect(LEFT_ENC_B, GPIO.BOTH, callback=left_encoder_callback)

GPIO.add_event_detect(RIGHT_ENC_A, GPIO.BOTH, callback=right_encoder_callback)
GPIO.add_event_detect(RIGHT_ENC_B, GPIO.BOTH, callback=right_encoder_callback)


# =========================
# 서보 제어
# =========================

def set_servo_angle(angle):
    global current_servo_angle

    current_servo_angle = clamp_angle(angle)
    duty = angle_to_duty(current_servo_angle)

    print(f"[{UNIT_NAME}] Servo angle = {current_servo_angle} deg, duty = {duty:.2f}%")

    servo_pwm.ChangeDutyCycle(duty)

    if not SERVO_HOLD:
        time.sleep(0.05)
        servo_pwm.ChangeDutyCycle(0)


def servo_up_step():
    set_servo_angle(current_servo_angle + SERVO_STEP_ANGLE)


def servo_down_step():
    set_servo_angle(current_servo_angle - SERVO_STEP_ANGLE)


# =========================
# 모터 방향 제어
# =========================

def apply_left_direction(direction):
    if direction == "forward":
        GPIO.output(IN1_PIN, GPIO.HIGH)
        GPIO.output(IN2_PIN, GPIO.LOW)
    elif direction == "backward":
        GPIO.output(IN1_PIN, GPIO.LOW)
        GPIO.output(IN2_PIN, GPIO.HIGH)
    else:
        GPIO.output(IN1_PIN, GPIO.LOW)
        GPIO.output(IN2_PIN, GPIO.LOW)


def apply_right_direction(direction):
    if direction == "forward":
        GPIO.output(IN3_PIN, GPIO.HIGH)
        GPIO.output(IN4_PIN, GPIO.LOW)
    elif direction == "backward":
        GPIO.output(IN3_PIN, GPIO.LOW)
        GPIO.output(IN4_PIN, GPIO.HIGH)
    else:
        GPIO.output(IN3_PIN, GPIO.LOW)
        GPIO.output(IN4_PIN, GPIO.LOW)


def set_drive_target(left_cps, left_dir, right_cps, right_dir):
    global left_target_cps, right_target_cps
    global left_direction, right_direction
    global left_integral, right_integral
    global left_prev_error, right_prev_error

    left_target_cps = abs(float(left_cps))
    right_target_cps = abs(float(right_cps))

    left_direction = left_dir
    right_direction = right_dir

    apply_left_direction(left_direction)
    apply_right_direction(right_direction)

    if left_target_cps == 0:
        left_integral = 0.0
        left_prev_error = 0.0

    if right_target_cps == 0:
        right_integral = 0.0
        right_prev_error = 0.0


def stop_all():
    global left_target_cps, right_target_cps
    global left_pwm_value, right_pwm_value
    global left_integral, right_integral
    global left_prev_error, right_prev_error

    left_target_cps = 0.0
    right_target_cps = 0.0

    left_pwm_value = 0.0
    right_pwm_value = 0.0

    left_integral = 0.0
    right_integral = 0.0
    left_prev_error = 0.0
    right_prev_error = 0.0

    apply_left_direction("stop")
    apply_right_direction("stop")

    pwm_left.ChangeDutyCycle(0)
    pwm_right.ChangeDutyCycle(0)


# =========================
# 주행 명령
# =========================

def forward():
    set_drive_target(
        FULL_SPEED_CPS_LEFT,
        "forward",
        FULL_SPEED_CPS_RIGHT,
        "forward"
    )


def backward():
    set_drive_target(
        FULL_SPEED_CPS_LEFT,
        "backward",
        FULL_SPEED_CPS_RIGHT,
        "backward"
    )


def forward_left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_INNER_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * TURN_OUTER_RATIO,
        "forward"
    )


def forward_right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_OUTER_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * TURN_INNER_RATIO,
        "forward"
    )


def backward_left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_OUTER_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * TURN_INNER_RATIO,
        "backward"
    )


def backward_right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_INNER_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * TURN_OUTER_RATIO,
        "backward"
    )


def left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * SPIN_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * SPIN_RATIO,
        "forward"
    )


def right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * SPIN_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * SPIN_RATIO,
        "backward"
    )


# =========================
# PID 제어 루프
# =========================

def compute_pid_pwm(target_cps, measured_cps, max_cps, kp, ki, kd, integral, prev_error, dt):
    if target_cps <= 0:
        return 0.0, 0.0, 0.0

    error = target_cps - measured_cps
    integral += error * dt
    integral = clamp(integral, -500.0, 500.0)

    derivative = (error - prev_error) / dt if dt > 0 else 0.0

    base_pwm = MIN_PWM + (target_cps / max_cps) * (MAX_PWM - MIN_PWM)
    pid_output = (kp * error) + (ki * integral) + (kd * derivative)

    pwm = base_pwm + pid_output
    pwm = clamp_pwm(pwm)

    return pwm, integral, error


def control_loop():
    global left_pwm_value, right_pwm_value
    global left_integral, right_integral
    global left_prev_error, right_prev_error
    global last_debug_time

    prev_left_count = 0
    prev_right_count = 0
    prev_time = time.time()

    while running:
        time.sleep(CONTROL_INTERVAL)

        now = time.time()
        dt = now - prev_time

        if dt <= 0:
            continue

        with encoder_lock:
            current_left_count = left_count
            current_right_count = right_count

        delta_left = current_left_count - prev_left_count
        delta_right = current_right_count - prev_right_count

        prev_left_count = current_left_count
        prev_right_count = current_right_count
        prev_time = now

        measured_left_cps = abs(delta_left) / dt
        measured_right_cps = abs(delta_right) / dt

        left_pwm_value, left_integral, left_prev_error = compute_pid_pwm(
            left_target_cps,
            measured_left_cps,
            FULL_SPEED_CPS_LEFT,
            KP_LEFT,
            KI_LEFT,
            KD_LEFT,
            left_integral,
            left_prev_error,
            dt
        )

        right_pwm_value, right_integral, right_prev_error = compute_pid_pwm(
            right_target_cps,
            measured_right_cps,
            FULL_SPEED_CPS_RIGHT,
            KP_RIGHT,
            KI_RIGHT,
            KD_RIGHT,
            right_integral,
            right_prev_error,
            dt
        )

        if left_target_cps <= 0:
            pwm_left.ChangeDutyCycle(0)
        else:
            pwm_left.ChangeDutyCycle(left_pwm_value)

        if right_target_cps <= 0:
            pwm_right.ChangeDutyCycle(0)
        else:
            pwm_right.ChangeDutyCycle(right_pwm_value)

        if now - last_debug_time >= DEBUG_PRINT_INTERVAL:
            last_debug_time = now
            print(
                f"[{UNIT_NAME}] "
                f"L target={left_target_cps:.1f} cps, measured={measured_left_cps:.1f} cps, pwm={left_pwm_value:.1f} | "
                f"R target={right_target_cps:.1f} cps, measured={measured_right_cps:.1f} cps, pwm={right_pwm_value:.1f}"
            )


# =========================
# 명령 처리
# =========================

def handle_command(command):
    command = command.strip().lower()

    if command == "":
        return

    print(f"[{UNIT_NAME}] Received command: {command}")

    if command == "forward":
        forward()

    elif command == "backward":
        backward()

    elif command == "forward_left":
        forward_left()

    elif command == "forward_right":
        forward_right()

    elif command == "backward_left":
        backward_left()

    elif command == "backward_right":
        backward_right()

    elif command == "left":
        left()

    elif command == "right":
        right()

    elif command == "stop":
        stop_all()

    elif command == "servo_up_step":
        servo_up_step()

    elif command == "servo_down_step":
        servo_down_step()

    else:
        print(f"[{UNIT_NAME}] Unknown command: {command}")


# =========================
# 서버 실행
# =========================

def main():
    global running

    print("====================================")
    print(f" {UNIT_NAME} Motor PID + Encoder + Servo Server")
    print("====================================")
    print(f"Listening on {HOST}:{PORT}")
    print("Encoder pins:")
    print(f"  LEFT  A/B = GPIO{LEFT_ENC_A}, GPIO{LEFT_ENC_B}")
    print(f"  RIGHT A/B = GPIO{RIGHT_ENC_A}, GPIO{RIGHT_ENC_B}")
    print("Drive commands:")
    print("  forward")
    print("  backward")
    print("  forward_left")
    print("  forward_right")
    print("  backward_left")
    print("  backward_right")
    print("  left")
    print("  right")
    print("  stop")
    print("Servo commands:")
    print("  servo_up_step")
    print("  servo_down_step")
    print("====================================")

    stop_all()

    if START_SERVO_CENTER_ON_BOOT:
        set_servo_angle(SERVO_CENTER_ANGLE)

    pid_thread = threading.Thread(target=control_loop)
    pid_thread.daemon = True
    pid_thread.start()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)

        while True:
            client_socket, client_address = server_socket.accept()

            with client_socket:
                data = client_socket.recv(1024)

                if not data:
                    continue

                command = data.decode(errors="ignore").strip()
                handle_command(command)

    except KeyboardInterrupt:
        print()
        print(f"[{UNIT_NAME}] KeyboardInterrupt detected.")

    except OSError as e:
        print(f"[{UNIT_NAME}] Socket error: {e}")
        print("Try:")
        print("pkill -f Head_control.py")

    finally:
        running = False
        time.sleep(0.1)

        stop_all()

        try:
            GPIO.remove_event_detect(LEFT_ENC_A)
            GPIO.remove_event_detect(LEFT_ENC_B)
            GPIO.remove_event_detect(RIGHT_ENC_A)
            GPIO.remove_event_detect(RIGHT_ENC_B)
        except Exception:
            pass

        try:
            pwm_left.stop()
            pwm_right.stop()
            servo_pwm.ChangeDutyCycle(0)
            servo_pwm.stop()
        except Exception:
            pass

        GPIO.cleanup()

        try:
            server_socket.close()
        except Exception:
            pass

        print(f"[{UNIT_NAME}] Server stopped safely.")


if __name__ == "__main__":
    main()

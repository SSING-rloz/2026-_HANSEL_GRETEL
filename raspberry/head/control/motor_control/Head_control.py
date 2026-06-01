import socket
import time
import threading
import RPi.GPIO as GPIO

UNIT_NAME = "HEAD"

# ============================================================
# Main drive motor driver pins
# ============================================================

ENA_PIN = 18
IN1_PIN = 23
IN2_PIN = 24

ENB_PIN = 13
IN3_PIN = 27
IN4_PIN = 22


# ============================================================
# Front head-unit DC motors
# ============================================================
# 고개가 들리는 앞쪽 유닛에 달린 DC모터 2개 제어용 핀.
# 별도 모터드라이버 1개 추가 연결 기준.
#
# FRONT_ENA_PIN / FRONT_IN1_PIN / FRONT_IN2_PIN = 앞쪽 왼쪽 DC모터
# FRONT_ENB_PIN / FRONT_IN3_PIN / FRONT_IN4_PIN = 앞쪽 오른쪽 DC모터
#
# C 키를 누르고 있는 동안만 keyboard.py가 "front_motor_forward"를 보내고,
# C 키를 떼면 "front_motor_stop"을 보낸다.

FRONT_MOTOR_ENABLED = True

FRONT_ENA_PIN = 12
FRONT_IN1_PIN = 4
FRONT_IN2_PIN = 25

FRONT_ENB_PIN = 19
FRONT_IN3_PIN = 5
FRONT_IN4_PIN = 7

# 앞쪽 모터 방향이 반대로 돌면 True로 바꾸기
FRONT_LEFT_REVERSE = False
FRONT_RIGHT_REVERSE = False

# C 키로 앞쪽 DC모터를 따로 돌릴 때 사용할 PWM
FRONT_MOTOR_KEY_PWM = 100

# False면 앞쪽 DC모터는 주행 명령을 따라가지 않고 C 키 명령으로만 동작
# True면 기존 헤드 좌/우 모터 PWM을 따라감
FRONT_MOTOR_FOLLOW_DRIVE = False

# FRONT_MOTOR_FOLLOW_DRIVE=True일 때 기존 헤드 바퀴 PWM 대비 속도 비율
FRONT_MOTOR_SPEED_RATIO = 1.0


# ============================================================
# Encoder pins
# ============================================================

LEFT_ENC_A = 20
LEFT_ENC_B = 21

RIGHT_ENC_A = 16
RIGHT_ENC_B = 26


# ============================================================
# Servo pins
# ============================================================

HEAD_SERVO_PIN = 17
DETACH_SERVO_PIN = 6


# ============================================================
# UDP server settings
# ============================================================

HOST = "0.0.0.0"
PORT = 5000
UDP_BUFFER_SIZE = 1024


# ============================================================
# PWM / PID settings
# ============================================================

PWM_FREQ = 1000
CONTROL_INTERVAL = 0.05

MIN_PWM = 25
MAX_PWM = 100
OPEN_LOOP_PWM = 55.0  # fallback duty cycle when encoder is unavailable

FULL_SPEED_CPS_LEFT = 800.0
FULL_SPEED_CPS_RIGHT = 800.0

TURN_INNER_RATIO = 0.45
TURN_OUTER_RATIO = 1.00

MILD_TURN_INNER_RATIO = 0.75
MILD_TURN_OUTER_RATIO = 1.00

SPIN_RATIO = 0.85

KP_LEFT = 0.035
KI_LEFT = 0.015
KD_LEFT = 0.000

KP_RIGHT = 0.035
KI_RIGHT = 0.015
KD_RIGHT = 0.000


# ============================================================
# Servo settings
# ============================================================

SERVO_FREQ = 50

current_head_servo_angle = 90

HEAD_SERVO_MIN_ANGLE = 40
HEAD_SERVO_MAX_ANGLE = 180
HEAD_SERVO_CENTER_ANGLE = 90
HEAD_SERVO_STEP_ANGLE = 2

START_HEAD_SERVO_CENTER_ON_BOOT = True
HEAD_SERVO_HOLD = True

current_detach_servo_angle = 20

DETACH_SERVO_MIN_ANGLE = 0
DETACH_SERVO_MAX_ANGLE = 180
DETACH_REST_ANGLE = 20
DETACH_PRESS_ANGLE = 75
DETACH_PRESS_TIME = 0.35

START_DETACH_SERVO_REST_ON_BOOT = True
DETACH_SERVO_HOLD = False


# ============================================================
# Global state
# ============================================================

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


def check_duplicate_pins():
    pin_map = {
        "ENA_PIN": ENA_PIN,
        "IN1_PIN": IN1_PIN,
        "IN2_PIN": IN2_PIN,
        "ENB_PIN": ENB_PIN,
        "IN3_PIN": IN3_PIN,
        "IN4_PIN": IN4_PIN,
        "LEFT_ENC_A": LEFT_ENC_A,
        "LEFT_ENC_B": LEFT_ENC_B,
        "RIGHT_ENC_A": RIGHT_ENC_A,
        "RIGHT_ENC_B": RIGHT_ENC_B,
        "HEAD_SERVO_PIN": HEAD_SERVO_PIN,
        "DETACH_SERVO_PIN": DETACH_SERVO_PIN,
    }

    if FRONT_MOTOR_ENABLED:
        pin_map.update(
            {
                "FRONT_ENA_PIN": FRONT_ENA_PIN,
                "FRONT_IN1_PIN": FRONT_IN1_PIN,
                "FRONT_IN2_PIN": FRONT_IN2_PIN,
                "FRONT_ENB_PIN": FRONT_ENB_PIN,
                "FRONT_IN3_PIN": FRONT_IN3_PIN,
                "FRONT_IN4_PIN": FRONT_IN4_PIN,
            }
        )

    used = {}

    for name, pin in pin_map.items():
        if pin in used:
            raise RuntimeError(
                f"GPIO pin conflict: {name} and {used[pin]} both use GPIO{pin}"
            )
        used[pin] = name

    print(f"[{UNIT_NAME}] PIN CHECK OK. No duplicated GPIO pins.")


try:
    GPIO.cleanup()
except Exception:
    pass

check_duplicate_pins()

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(ENA_PIN, GPIO.OUT)
GPIO.setup(IN1_PIN, GPIO.OUT)
GPIO.setup(IN2_PIN, GPIO.OUT)

GPIO.setup(ENB_PIN, GPIO.OUT)
GPIO.setup(IN3_PIN, GPIO.OUT)
GPIO.setup(IN4_PIN, GPIO.OUT)

if FRONT_MOTOR_ENABLED:
    GPIO.setup(FRONT_ENA_PIN, GPIO.OUT)
    GPIO.setup(FRONT_IN1_PIN, GPIO.OUT)
    GPIO.setup(FRONT_IN2_PIN, GPIO.OUT)

    GPIO.setup(FRONT_ENB_PIN, GPIO.OUT)
    GPIO.setup(FRONT_IN3_PIN, GPIO.OUT)
    GPIO.setup(FRONT_IN4_PIN, GPIO.OUT)

GPIO.setup(LEFT_ENC_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LEFT_ENC_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(RIGHT_ENC_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(RIGHT_ENC_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(HEAD_SERVO_PIN, GPIO.OUT)
GPIO.setup(DETACH_SERVO_PIN, GPIO.OUT)

pwm_left = GPIO.PWM(ENA_PIN, PWM_FREQ)
pwm_right = GPIO.PWM(ENB_PIN, PWM_FREQ)

front_pwm_left = None
front_pwm_right = None

if FRONT_MOTOR_ENABLED:
    front_pwm_left = GPIO.PWM(FRONT_ENA_PIN, PWM_FREQ)
    front_pwm_right = GPIO.PWM(FRONT_ENB_PIN, PWM_FREQ)

head_servo_pwm = GPIO.PWM(HEAD_SERVO_PIN, SERVO_FREQ)
detach_servo_pwm = GPIO.PWM(DETACH_SERVO_PIN, SERVO_FREQ)

pwm_left.start(0)
pwm_right.start(0)

if FRONT_MOTOR_ENABLED:
    front_pwm_left.start(0)
    front_pwm_right.start(0)

head_servo_pwm.start(0)
detach_servo_pwm.start(0)


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def clamp_pwm(value):
    return clamp(value, 0, 100)


def clamp_angle(angle, min_angle=0, max_angle=180):
    return int(clamp(angle, min_angle, max_angle))


def angle_to_duty(angle):
    angle = int(clamp(angle, 0, 180))
    return 2.5 + (angle / 18.0)


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

# Clear any stale kernel-level edge detection left by a previous process.
# RPi.GPIO.cleanup() does NOT clear /sys/class/gpio/gpioXX/edge, so we must:
#   1. export the pin (creates the sysfs files if not present)
#   2. write "none" to the edge file
#   3. unexport (so GPIO.setup can re-claim it cleanly)
import os as _os
for _enc_pin in (LEFT_ENC_A, LEFT_ENC_B, RIGHT_ENC_A, RIGHT_ENC_B):
    try:
        with open("/sys/class/gpio/export", "w") as _f:
            _f.write(str(_enc_pin))
    except OSError:
        pass  # already exported
    _edge = f"/sys/class/gpio/gpio{_enc_pin}/edge"
    if _os.path.exists(_edge):
        try:
            with open(_edge, "w") as _f:
                _f.write("none")
        except OSError:
            pass
    try:
        with open("/sys/class/gpio/unexport", "w") as _f:
            _f.write(str(_enc_pin))
    except OSError:
        pass
    try:
        GPIO.remove_event_detect(_enc_pin)
    except Exception:
        pass

ENCODER_AVAILABLE = True
try:
    GPIO.add_event_detect(LEFT_ENC_A, GPIO.BOTH, callback=left_encoder_callback)
    GPIO.add_event_detect(LEFT_ENC_B, GPIO.BOTH, callback=left_encoder_callback)
    GPIO.add_event_detect(RIGHT_ENC_A, GPIO.BOTH, callback=right_encoder_callback)
    GPIO.add_event_detect(RIGHT_ENC_B, GPIO.BOTH, callback=right_encoder_callback)
    print(f"[{UNIT_NAME}] Encoder edge detection OK")
except RuntimeError as e:
    ENCODER_AVAILABLE = False
    print(f"[{UNIT_NAME}] WARNING: encoder edge detection unavailable ({e})")
    print(f"[{UNIT_NAME}] Falling back to open-loop motor control (PWM={OPEN_LOOP_PWM}%)")


def set_head_servo_angle(angle):
    global current_head_servo_angle

    current_head_servo_angle = clamp_angle(
        angle,
        HEAD_SERVO_MIN_ANGLE,
        HEAD_SERVO_MAX_ANGLE,
    )

    duty = angle_to_duty(current_head_servo_angle)

    print(f"[{UNIT_NAME}] Head servo angle={current_head_servo_angle}, duty={duty:.2f}%")

    head_servo_pwm.ChangeDutyCycle(duty)

    if not HEAD_SERVO_HOLD:
        time.sleep(0.05)
        head_servo_pwm.ChangeDutyCycle(0)


def head_servo_up_step():
    set_head_servo_angle(current_head_servo_angle + HEAD_SERVO_STEP_ANGLE)


def head_servo_down_step():
    set_head_servo_angle(current_head_servo_angle - HEAD_SERVO_STEP_ANGLE)


def servo_up_step():
    head_servo_up_step()


def servo_down_step():
    head_servo_down_step()


def set_detach_servo_angle(angle, hold=None):
    global current_detach_servo_angle

    if hold is None:
        hold = DETACH_SERVO_HOLD

    current_detach_servo_angle = clamp_angle(
        angle,
        DETACH_SERVO_MIN_ANGLE,
        DETACH_SERVO_MAX_ANGLE,
    )

    duty = angle_to_duty(current_detach_servo_angle)

    print(f"[{UNIT_NAME}] Detach servo angle={current_detach_servo_angle}, duty={duty:.2f}%")

    detach_servo_pwm.ChangeDutyCycle(duty)

    if not hold:
        time.sleep(0.12)
        detach_servo_pwm.ChangeDutyCycle(0)


def detach_servo_rest():
    print(f"[{UNIT_NAME}] Detach servo rest")
    set_detach_servo_angle(DETACH_REST_ANGLE, hold=False)


def detach_servo_press():
    print(f"[{UNIT_NAME}] Detach button press")

    set_detach_servo_angle(DETACH_PRESS_ANGLE, hold=True)
    time.sleep(DETACH_PRESS_TIME)
    set_detach_servo_angle(DETACH_REST_ANGLE, hold=False)


def reverse_direction_if_needed(direction, reverse):
    if not reverse:
        return direction

    if direction == "forward":
        return "backward"

    if direction == "backward":
        return "forward"

    return "stop"


def apply_front_left_direction(direction):
    if not FRONT_MOTOR_ENABLED:
        return

    direction = reverse_direction_if_needed(direction, FRONT_LEFT_REVERSE)

    if direction == "forward":
        GPIO.output(FRONT_IN1_PIN, GPIO.HIGH)
        GPIO.output(FRONT_IN2_PIN, GPIO.LOW)
    elif direction == "backward":
        GPIO.output(FRONT_IN1_PIN, GPIO.LOW)
        GPIO.output(FRONT_IN2_PIN, GPIO.HIGH)
    else:
        GPIO.output(FRONT_IN1_PIN, GPIO.LOW)
        GPIO.output(FRONT_IN2_PIN, GPIO.LOW)


def apply_front_right_direction(direction):
    if not FRONT_MOTOR_ENABLED:
        return

    direction = reverse_direction_if_needed(direction, FRONT_RIGHT_REVERSE)

    if direction == "forward":
        GPIO.output(FRONT_IN3_PIN, GPIO.HIGH)
        GPIO.output(FRONT_IN4_PIN, GPIO.LOW)
    elif direction == "backward":
        GPIO.output(FRONT_IN3_PIN, GPIO.LOW)
        GPIO.output(FRONT_IN4_PIN, GPIO.HIGH)
    else:
        GPIO.output(FRONT_IN3_PIN, GPIO.LOW)
        GPIO.output(FRONT_IN4_PIN, GPIO.LOW)


def apply_front_pwm(left_pwm, right_pwm):
    if not FRONT_MOTOR_ENABLED:
        return

    safe_left_pwm = clamp_pwm(left_pwm)
    safe_right_pwm = clamp_pwm(right_pwm)

    front_pwm_left.ChangeDutyCycle(safe_left_pwm)
    front_pwm_right.ChangeDutyCycle(safe_right_pwm)


def stop_front_motors():
    if not FRONT_MOTOR_ENABLED:
        return

    apply_front_left_direction("stop")
    apply_front_right_direction("stop")
    apply_front_pwm(0, 0)


def front_motor_forward():
    if not FRONT_MOTOR_ENABLED:
        print(f"[{UNIT_NAME}] FRONT_MOTOR_ENABLED is False")
        return

    print(f"[{UNIT_NAME}] Front motor: forward")
    apply_front_left_direction("forward")
    apply_front_right_direction("forward")
    apply_front_pwm(FRONT_MOTOR_KEY_PWM, FRONT_MOTOR_KEY_PWM)


def front_motor_backward():
    if not FRONT_MOTOR_ENABLED:
        print(f"[{UNIT_NAME}] FRONT_MOTOR_ENABLED is False")
        return

    print(f"[{UNIT_NAME}] Front motor: backward")
    apply_front_left_direction("backward")
    apply_front_right_direction("backward")
    apply_front_pwm(FRONT_MOTOR_KEY_PWM, FRONT_MOTOR_KEY_PWM)


def front_motor_stop():
    print(f"[{UNIT_NAME}] Front motor: stop")
    stop_front_motors()


def front_forward_test():
    front_motor_forward()


def front_backward_test():
    front_motor_backward()


def front_stop_test():
    front_motor_stop()


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

    if FRONT_MOTOR_ENABLED and FRONT_MOTOR_FOLLOW_DRIVE:
        apply_front_left_direction(left_direction)
        apply_front_right_direction(right_direction)

    if left_target_cps == 0:
        left_integral = 0.0
        left_prev_error = 0.0

    if right_target_cps == 0:
        right_integral = 0.0
        right_prev_error = 0.0


def stop_drive_motors():
    apply_left_direction("stop")
    apply_right_direction("stop")

    pwm_left.ChangeDutyCycle(0)
    pwm_right.ChangeDutyCycle(0)


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

    stop_drive_motors()
    stop_front_motors()


def forward():
    set_drive_target(FULL_SPEED_CPS_LEFT, "forward", FULL_SPEED_CPS_RIGHT, "forward")


def backward():
    set_drive_target(FULL_SPEED_CPS_LEFT, "backward", FULL_SPEED_CPS_RIGHT, "backward")


def forward_left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_INNER_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * TURN_OUTER_RATIO,
        "forward",
    )


def forward_right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_OUTER_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * TURN_INNER_RATIO,
        "forward",
    )


def backward_left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_OUTER_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * TURN_INNER_RATIO,
        "backward",
    )


def backward_right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * TURN_INNER_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * TURN_OUTER_RATIO,
        "backward",
    )


def mild_forward_left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * MILD_TURN_INNER_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * MILD_TURN_OUTER_RATIO,
        "forward",
    )


def mild_forward_right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * MILD_TURN_OUTER_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * MILD_TURN_INNER_RATIO,
        "forward",
    )


def mild_backward_left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * MILD_TURN_OUTER_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * MILD_TURN_INNER_RATIO,
        "backward",
    )


def mild_backward_right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * MILD_TURN_INNER_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * MILD_TURN_OUTER_RATIO,
        "backward",
    )


def left():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * SPIN_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * SPIN_RATIO,
        "forward",
    )


def right():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * SPIN_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * SPIN_RATIO,
        "backward",
    )


def compute_pid_pwm(target_cps, measured_cps, max_cps, kp, ki, kd, integral, prev_error, dt):
    if target_cps <= 0:
        return 0.0, 0.0, 0.0

    error = target_cps - measured_cps

    integral += error * dt
    integral = clamp(integral, -500.0, 500.0)

    derivative = (error - prev_error) / dt if dt > 0 else 0.0

    base_pwm = MIN_PWM + (target_cps / max_cps) * (MAX_PWM - MIN_PWM)
    pid_output = (kp * error) + (ki * integral) + (kd * derivative)

    pwm = clamp_pwm(base_pwm + pid_output)

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

        if ENCODER_AVAILABLE:
            left_pwm_value, left_integral, left_prev_error = compute_pid_pwm(
                left_target_cps,
                measured_left_cps,
                FULL_SPEED_CPS_LEFT,
                KP_LEFT,
                KI_LEFT,
                KD_LEFT,
                left_integral,
                left_prev_error,
                dt,
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
                dt,
            )
        else:
            # Open-loop fallback: fixed PWM when moving, 0 when stopped
            left_pwm_value = OPEN_LOOP_PWM if left_target_cps > 0 else 0.0
            right_pwm_value = OPEN_LOOP_PWM if right_target_cps > 0 else 0.0

        pwm_left.ChangeDutyCycle(0 if left_target_cps <= 0 else left_pwm_value)
        pwm_right.ChangeDutyCycle(0 if right_target_cps <= 0 else right_pwm_value)

        if FRONT_MOTOR_ENABLED and FRONT_MOTOR_FOLLOW_DRIVE:
            front_left_pwm_value = 0 if left_target_cps <= 0 else left_pwm_value * FRONT_MOTOR_SPEED_RATIO
            front_right_pwm_value = 0 if right_target_cps <= 0 else right_pwm_value * FRONT_MOTOR_SPEED_RATIO
            apply_front_pwm(front_left_pwm_value, front_right_pwm_value)

        if now - last_debug_time >= DEBUG_PRINT_INTERVAL:
            last_debug_time = now
            print(
                f"[{UNIT_NAME}] "
                f"L target={left_target_cps:.1f} cps, measured={measured_left_cps:.1f} cps, pwm={left_pwm_value:.1f} | "
                f"R target={right_target_cps:.1f} cps, measured={measured_right_cps:.1f} cps, pwm={right_pwm_value:.1f}"
            )


def handle_command(command):
    command = command.strip().lower()

    if command == "":
        return

    print(f"[{UNIT_NAME}] Received command: {command}")

    command_map = {
        "forward": forward,
        "backward": backward,
        "forward_left": forward_left,
        "forward_right": forward_right,
        "backward_left": backward_left,
        "backward_right": backward_right,
        "mild_forward_left": mild_forward_left,
        "mild_forward_right": mild_forward_right,
        "mild_backward_left": mild_backward_left,
        "mild_backward_right": mild_backward_right,
        "left": left,
        "right": right,
        "stop": stop_all,
        "servo_up_step": servo_up_step,
        "servo_down_step": servo_down_step,
        "head_up_step": head_servo_up_step,
        "head_down_step": head_servo_down_step,
        "detach_press": detach_servo_press,
        "detach_rest": detach_servo_rest,
        "front_motor_forward": front_motor_forward,
        "front_motor_backward": front_motor_backward,
        "front_motor_stop": front_motor_stop,
        "front_forward_test": front_forward_test,
        "front_backward_test": front_backward_test,
        "front_stop_test": front_stop_test,
    }

    action = command_map.get(command)

    if action is None:
        print(f"[{UNIT_NAME}] Unknown command: {command}")
        return

    action()


def main():
    global running

    print("====================================")
    print(f" {UNIT_NAME} UDP Motor PID + Encoder + Head Servo + Detach Servo Server")
    print("====================================")
    print(f"Listening UDP on {HOST}:{PORT}")
    print(f"LEFT Encoder A/B = GPIO{LEFT_ENC_A}, GPIO{LEFT_ENC_B}")
    print(f"RIGHT Encoder A/B = GPIO{RIGHT_ENC_A}, GPIO{RIGHT_ENC_B}")
    print(f"HEAD SERVO = GPIO{HEAD_SERVO_PIN}, physical pin 32")
    print(f"DETACH SERVO = GPIO{DETACH_SERVO_PIN}, physical pin 31")

    if FRONT_MOTOR_ENABLED:
        print(
            "FRONT MOTORS = "
            f"L(ENA GPIO{FRONT_ENA_PIN}, IN1 GPIO{FRONT_IN1_PIN}, IN2 GPIO{FRONT_IN2_PIN}) / "
            f"R(ENB GPIO{FRONT_ENB_PIN}, IN3 GPIO{FRONT_IN3_PIN}, IN4 GPIO{FRONT_IN4_PIN})"
        )
        print(f"FRONT_MOTOR_KEY_PWM = {FRONT_MOTOR_KEY_PWM}")
        print(f"FRONT_MOTOR_FOLLOW_DRIVE = {FRONT_MOTOR_FOLLOW_DRIVE}")
    else:
        print("FRONT MOTORS = disabled")

    print("====================================")

    stop_all()

    if START_HEAD_SERVO_CENTER_ON_BOOT:
        set_head_servo_angle(HEAD_SERVO_CENTER_ANGLE)

    if START_DETACH_SERVO_REST_ON_BOOT:
        detach_servo_rest()

    pid_thread = threading.Thread(target=control_loop)
    pid_thread.daemon = True
    pid_thread.start()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
        print(f"[{UNIT_NAME}] UDP server ready on {HOST}:{PORT}")

        while True:
            data, client_address = server_socket.recvfrom(UDP_BUFFER_SIZE)

            if not data:
                continue

            command = data.decode(errors="ignore").strip()
            print(f"[{UNIT_NAME}] UDP from {client_address}: {command}")

            handle_command(command)

    except KeyboardInterrupt:
        print()
        print(f"[{UNIT_NAME}] KeyboardInterrupt detected.")

    except OSError as e:
        print(f"[{UNIT_NAME}] Socket error: {e}")
        print("Try: sudo pkill -f Head_control.py")

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
            pwm_left.ChangeDutyCycle(0)
            pwm_right.ChangeDutyCycle(0)

            if FRONT_MOTOR_ENABLED:
                front_pwm_left.ChangeDutyCycle(0)
                front_pwm_right.ChangeDutyCycle(0)

            head_servo_pwm.ChangeDutyCycle(0)
            detach_servo_pwm.ChangeDutyCycle(0)
        except Exception:
            pass

        try:
            pwm_left.stop()
            pwm_right.stop()

            if FRONT_MOTOR_ENABLED:
                front_pwm_left.stop()
                front_pwm_right.stop()

            head_servo_pwm.stop()
            detach_servo_pwm.stop()
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
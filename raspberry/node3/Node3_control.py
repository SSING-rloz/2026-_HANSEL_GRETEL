import socket
import time
import threading
import RPi.GPIO as GPIO

UNIT_NAME = "NODE3"

ENA_PIN = 18
IN1_PIN = 23
IN2_PIN = 24
ENB_PIN = 13
IN3_PIN = 27
IN4_PIN = 22

LEFT_ENC_A = 20
LEFT_ENC_B = 21
RIGHT_ENC_A = 16
RIGHT_ENC_B = 26

DETACH_SERVO_PIN = 6

HOST = "0.0.0.0"
PORT = 5000
UDP_BUFFER_SIZE = 1024

PWM_FREQ = 1000
CONTROL_INTERVAL = 0.05
MIN_PWM = 25
MAX_PWM = 100

FULL_SPEED_CPS_LEFT = 800.0
FULL_SPEED_CPS_RIGHT = 800.0

NODE_SLOW_RATIO = 0.35

KP_LEFT = 0.035
KI_LEFT = 0.015
KD_LEFT = 0.000
KP_RIGHT = 0.035
KI_RIGHT = 0.015
KD_RIGHT = 0.000

SERVO_FREQ = 50

current_detach_servo_angle = 20
DETACH_SERVO_MIN_ANGLE = 0
DETACH_SERVO_MAX_ANGLE = 180
DETACH_REST_ANGLE = 20
DETACH_PRESS_ANGLE = 75
DETACH_PRESS_TIME = 0.35
START_DETACH_SERVO_REST_ON_BOOT = True
DETACH_SERVO_HOLD = False

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
        "DETACH_SERVO_PIN": DETACH_SERVO_PIN,
    }
    used = {}
    for name, pin in pin_map.items():
        if pin in used:
            raise RuntimeError(f"GPIO pin conflict: {name} and {used[pin]} both use GPIO{pin}")
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

GPIO.setup(LEFT_ENC_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LEFT_ENC_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(RIGHT_ENC_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(RIGHT_ENC_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(DETACH_SERVO_PIN, GPIO.OUT)

pwm_left = GPIO.PWM(ENA_PIN, PWM_FREQ)
pwm_right = GPIO.PWM(ENB_PIN, PWM_FREQ)
detach_servo_pwm = GPIO.PWM(DETACH_SERVO_PIN, SERVO_FREQ)

pwm_left.start(0)
pwm_right.start(0)
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

GPIO.add_event_detect(LEFT_ENC_A, GPIO.BOTH, callback=left_encoder_callback)
GPIO.add_event_detect(LEFT_ENC_B, GPIO.BOTH, callback=left_encoder_callback)
GPIO.add_event_detect(RIGHT_ENC_A, GPIO.BOTH, callback=right_encoder_callback)
GPIO.add_event_detect(RIGHT_ENC_B, GPIO.BOTH, callback=right_encoder_callback)


def set_detach_servo_angle(angle, hold=None):
    global current_detach_servo_angle
    if hold is None:
        hold = DETACH_SERVO_HOLD
    current_detach_servo_angle = clamp_angle(angle, DETACH_SERVO_MIN_ANGLE, DETACH_SERVO_MAX_ANGLE)
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


def forward():
    set_drive_target(FULL_SPEED_CPS_LEFT, "forward", FULL_SPEED_CPS_RIGHT, "forward")


def backward():
    set_drive_target(FULL_SPEED_CPS_LEFT, "backward", FULL_SPEED_CPS_RIGHT, "backward")


def slow_forward():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * NODE_SLOW_RATIO,
        "forward",
        FULL_SPEED_CPS_RIGHT * NODE_SLOW_RATIO,
        "forward",
    )


def slow_backward():
    set_drive_target(
        FULL_SPEED_CPS_LEFT * NODE_SLOW_RATIO,
        "backward",
        FULL_SPEED_CPS_RIGHT * NODE_SLOW_RATIO,
        "backward",
    )


def left():
    stop_all()


def right():
    stop_all()


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

        pwm_left.ChangeDutyCycle(0 if left_target_cps <= 0 else left_pwm_value)
        pwm_right.ChangeDutyCycle(0 if right_target_cps <= 0 else right_pwm_value)

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
        "slow_forward": slow_forward,
        "slow_backward": slow_backward,
        "left": left,
        "right": right,
        "stop": stop_all,
        "detach_press": detach_servo_press,
        "detach_rest": detach_servo_rest,
    }

    action = command_map.get(command)

    if action is None:
        print(f"[{UNIT_NAME}] Unknown command: {command}")
        return

    action()


def main():
    global running

    print("====================================")
    print(f" {UNIT_NAME} UDP Motor PID + Encoder + Detach Servo Server")
    print("====================================")
    print(f"Listening UDP on {HOST}:{PORT}")
    print(f"LEFT Encoder A/B = GPIO{LEFT_ENC_A}, GPIO{LEFT_ENC_B}")
    print(f"RIGHT Encoder A/B = GPIO{RIGHT_ENC_A}, GPIO{RIGHT_ENC_B}")
    print(f"DETACH SERVO = GPIO{DETACH_SERVO_PIN}, physical pin 31")
    print("====================================")

    stop_all()

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
        print(f"Try: sudo pkill -f {UNIT_NAME}_control.py")

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
            detach_servo_pwm.ChangeDutyCycle(0)
        except Exception:
            pass

        try:
            pwm_left.stop()
            pwm_right.stop()
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
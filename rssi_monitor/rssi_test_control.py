#!/usr/bin/env python3
# control.py  --  조종 노트북에서 실행
#
# 사용법:
#   python3 control.py start
#   python3 control.py start "udp://@0.0.0.0:5000"   # FPS 입력을 직접 지정할 때
#   python3 control.py stop
#
# start 실행 시:
#   1) 조종 노트북에서 monitor와 fps_logger를 먼저 실행합니다.
#   2) 노드1에게 START 명령을 보냅니다.
#
# stop 실행 시:
#   - 노드1에게 STOP 명령만 보냅니다.
#   - monitor는 STOP 후 올라오는 CSV 수신이 필요할 수 있으므로 자동 종료하지 않습니다.
#
# 노트북은 '하류 이웃(노드1)'에게만 명령을 보냅니다.
# 이후 노드1 -> 노드2 -> ... -> AP 로 릴레이가 알아서 전달합니다.

import os
import shlex
import shutil
import socket
import subprocess
import sys
import time

CMD_PORT = 5052
NODE1_IP = "192.168.0.2"   # ★ 노트북의 이웃(노드1) IP 로 변경하세요

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(SCRIPT_DIR, ".control_runtime")


def find_script(*names):
    """같은 폴더에서 실행할 보조 스크립트를 찾습니다."""
    for name in names:
        path = os.path.join(SCRIPT_DIR, name)
        if os.path.exists(path):
            return path
    return os.path.join(SCRIPT_DIR, names[0])


FPS_LOGGER_SCRIPT = find_script("fps_logger.py")
MONITOR_SCRIPT = find_script("monitor.py", "monitor(1).py")


def send(cmd):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(cmd.encode(), (NODE1_IP, CMD_PORT))
    print(f"'{cmd}' 전송 -> 노드1({NODE1_IP}) → 하류로 릴레이됨")


def pid_file(name):
    return os.path.join(RUNTIME_DIR, f"{name}.pid")


def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def read_running_pid(name):
    path = pid_file(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        return pid if is_process_running(pid) else None
    except Exception:
        return None


def write_pid(name, pid):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(pid_file(name), "w", encoding="utf-8") as f:
        f.write(str(pid))


def shell_join(cmd):
    return " ".join(shlex.quote(str(x)) for x in cmd)


def terminal_command(title, cmd):
    """가능하면 새 터미널 창에서 실행하기 위한 명령을 만듭니다."""
    body = (
        f"cd {shlex.quote(SCRIPT_DIR)} && "
        f"{shell_join(cmd)}; "
        f"echo; echo '[{title}] 종료됨. Enter를 누르면 창을 닫습니다.'; read -r _"
    )

    if os.name == "nt":
        return None

    if sys.platform == "darwin" and shutil.which("osascript"):
        osa = (
            'tell application "Terminal" to do script '
            + shlex.quote(f"cd {SCRIPT_DIR} && {shell_join(cmd)}")
        )
        return ["osascript", "-e", osa]

    candidates = [
        ("gnome-terminal", ["gnome-terminal", "--title", title, "--", "bash", "-lc", body]),
        ("konsole", ["konsole", "--new-tab", "-p", f"tabtitle={title}", "-e", "bash", "-lc", body]),
        ("xterm", ["xterm", "-T", title, "-e", "bash", "-lc", body]),
    ]
    for exe, term_cmd in candidates:
        if shutil.which(exe):
            return term_cmd
    return None


def launch_tool(name, script_path, args=None):
    """monitor/fps_logger가 이미 실행 중이면 중복 실행하지 않고, 아니면 실행합니다."""
    args = args or []
    running_pid = read_running_pid(name)
    if running_pid is not None:
        print(f"[{name}] 이미 실행 중입니다. pid={running_pid}")
        return

    if not os.path.exists(script_path):
        print(f"[{name}] 실행 실패: 파일을 찾을 수 없습니다 -> {script_path}")
        return

    cmd = [sys.executable, script_path] + args
    os.makedirs(RUNTIME_DIR, exist_ok=True)

    if os.name == "nt":
        # Windows에서는 별도 콘솔 창으로 실행합니다.
        p = subprocess.Popen(
            cmd,
            cwd=SCRIPT_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        # Linux/macOS에서는 가능한 경우 별도 터미널 창으로 실행합니다.
        term_cmd = terminal_command(name, cmd)
        if term_cmd is not None:
            p = subprocess.Popen(term_cmd, cwd=SCRIPT_DIR, start_new_session=True)
        else:
            # GUI 터미널이 없으면 백그라운드로 실행하고 출력은 로그 파일에 저장합니다.
            log_path = os.path.join(RUNTIME_DIR, f"{name}.out")
            log = open(log_path, "a", encoding="utf-8")
            p = subprocess.Popen(
                cmd,
                cwd=SCRIPT_DIR,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            print(f"[{name}] 새 터미널을 찾지 못해 백그라운드 실행. 출력 로그: {log_path}")

    write_pid(name, p.pid)
    print(f"[{name}] 실행 시작. pid={p.pid}")


def start_local_tools(video_input=None):
    # monitor는 START 직후 들어오는 RSSI와 STOP 이후 CSV 수신을 놓치지 않도록 먼저 켭니다.
    launch_tool("monitor", MONITOR_SCRIPT)

    fps_args = [video_input] if video_input else []
    launch_tool("fps_logger", FPS_LOGGER_SCRIPT, fps_args)


def usage():
    print("사용법: python3 control.py start|stop [fps_video_input]")
    print("예시  : python3 control.py start")
    print('예시  : python3 control.py start "udp://@0.0.0.0:5000"')


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("start", "stop"):
        usage()
        sys.exit(1)

    cmd = sys.argv[1].upper()

    if cmd == "START":
        video_input = sys.argv[2] if len(sys.argv) >= 3 else None
        start_local_tools(video_input)
        time.sleep(0.3)  # monitor/fps_logger가 포트를 열 시간을 아주 짧게 줍니다.

    send(cmd)

#!/usr/bin/env python3
# control.py  --  조종 노트북에서 실행
#
# 사용법:
#   python3 control.py start
#   python3 control.py stop
#
# 노트북은 '하류 이웃(노드1)'에게만 명령을 보냅니다.
# 이후 노드1 -> 노드2 -> ... -> AP 로 릴레이가 알아서 전달합니다.

import socket, sys

CMD_PORT = 6002
NODE1_IP = "192.168.0.2"   # ★ 노트북의 이웃(노드1) IP 로 변경하세요


def send(cmd):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(cmd.encode(), (NODE1_IP, CMD_PORT))
    print(f"'{cmd}' 전송 -> 노드1({NODE1_IP}) → 하류로 릴레이됨")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("start", "stop"):
        print("사용법: python3 control.py start|stop")
        sys.exit(1)
    send(sys.argv[1].upper())

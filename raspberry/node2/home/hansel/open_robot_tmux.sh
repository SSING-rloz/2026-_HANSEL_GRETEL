#!/bin/bash

# ============================================================
# open_robot_tmux.sh
#
# tmux 4분할:
#   왼쪽 위    : HEAD
#   오른쪽 위  : NODE1
#   왼쪽 아래  : NODE2
#   오른쪽 아래: LOCAL KEYBOARD
#
# 비밀번호 1234 자동 입력
# ============================================================

SESSION="robot"

PI_PASSWORD="1234"

HEAD_HOST="pi@192.168.50.218"
NODE1_HOST="pi@192.168.50.252"
NODE2_HOST="pi@192.168.50.179"

SSH_CMD="sshpass -p $PI_PASSWORD ssh -o StrictHostKeyChecking=no -o ConnectTimeout=2"

# 기존 세션 종료
tmux has-session -t "$SESSION" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Existing tmux session '$SESSION' found. Killing it..."
    tmux kill-session -t "$SESSION"
fi

# 새 세션 생성: 왼쪽 위 HEAD pane
tmux new-session -d -s "$SESSION" -n control
PANE_HEAD=$(tmux display-message -p -t "$SESSION:0" "#{pane_id}")

# 오른쪽 위 NODE1 pane 생성
PANE_NODE1=$(tmux split-window -h -t "$PANE_HEAD" -P -F "#{pane_id}")

# 왼쪽 아래 NODE2 pane 생성
PANE_NODE2=$(tmux split-window -v -t "$PANE_HEAD" -P -F "#{pane_id}")

# 오른쪽 아래 KEYBOARD pane 생성
PANE_KEYBOARD=$(tmux split-window -v -t "$PANE_NODE1" -P -F "#{pane_id}")

# 보기 좋게 정렬
tmux select-layout -t "$SESSION:0" tiled

# 각 pane에 명령 전송
tmux send-keys -t "$PANE_HEAD" "$SSH_CMD $HEAD_HOST" C-m
tmux send-keys -t "$PANE_NODE1" "$SSH_CMD $NODE1_HOST" C-m
tmux send-keys -t "$PANE_NODE2" "$SSH_CMD $NODE2_HOST" C-m
tmux send-keys -t "$PANE_KEYBOARD" "echo 'Local keyboard terminal'; pwd" C-m

# pane 제목 설정
tmux select-pane -t "$PANE_HEAD" -T "HEAD"
tmux select-pane -t "$PANE_NODE1" -T "NODE1"
tmux select-pane -t "$PANE_NODE2" -T "NODE2"
tmux select-pane -t "$PANE_KEYBOARD" -T "KEYBOARD"

# HEAD pane 선택 후 접속
tmux select-pane -t "$PANE_HEAD"

tmux attach-session -t "$SESSION"

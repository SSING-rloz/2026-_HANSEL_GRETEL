// Field test checklist for HANSEL/GRETEL.
const h = require("./helpers");
const { H1, H2, H3, P, Bullet, Spacer, Rule, makeTable, Callout, TitlePage, build, COLORS } = h;

const c = [];

// ---- Title page ----
c.push(...TitlePage({
  title: ["HANSEL / GRETEL", "현장 시험 체크리스트"],
  subtitle: "Field Test Checklist — 분리형 군집 로봇",
  banner: [
    [{ t: "DRAFT — 최신 코드 기준 작성, 실물 end-to-end 검증 전", b: true }],
    [{ t: "각 항목을 실제 장비에서 순서대로 확인하고 결과/로그/조치를 기록하세요.", b: false }],
  ],
  bannerKind: "warn",
  meta: [
    "대상: Head, Node1, Node2, Node3, Android 조종 단말, PC 조종기",
    "작성 기준: origin/main 최신 코드 (pull 후)",
    "문서 버전: 초안 v1 — 현장 검증 후 갱신 예정",
  ],
}));

// ---- How to use ----
c.push(H1("0. 사용 방법"));
c.push(P([
  { t: "이 체크리스트는 " }, { t: "최초 설치", b: true },
  { t: "부터 " }, { t: "자동 분리", b: true },
  { t: "까지 현장에서 한 번에 점검하기 위한 표입니다. 각 행은 위에서 아래 순서로 수행하세요." },
]));
c.push(Bullet([{ t: "결과", b: true }, { t: " 열에는 ✅(성공) / ❌(실패) / ⚠(부분/보류) 중 하나를 적습니다." }]));
c.push(Bullet([{ t: "로그/근거", b: true }, { t: " 열에는 확인한 명령 출력·journalctl 로그·화면 상태 등 판단 근거를 적습니다." }]));
c.push(Bullet([{ t: "조치", b: true }, { t: " 열에는 실패 시 수행한 조치 또는 후속 작업을 적습니다." }]));
c.push(Callout("주의", [
  [{ t: "PC 조종기(keyboard.py) 기본 IP는 임시 SSH IP(10.180.86.x)입니다. AP 운용 시 반드시 환경변수로 192.168.4.x를 지정해야 명령이 로봇에 도달합니다.", b: false }],
], "warn"));
c.push(Spacer());

const W = [520, 3200, 2400, 1620, 1620];
function row(no, item, expect) {
  return [no, item, expect, "", ""];
}
const headRow = ["#", "점검 항목", "기대 결과 / 성공 기준", "결과", "로그·근거 / 조치"];

// ---- 1. 최초 설치 ----
c.push(H1("1. 최초 설치 · 클론 · 의존성"));
c.push(makeTable(W, [
  headRow,
  row("1.1", "각 Pi에 git 설치 확인 (git --version)", "버전 출력됨"),
  row("1.2", "저장소 클론 (git clone …/2026-_HANSEL_GRETEL)", "클론 성공, 디렉터리 생성"),
  row("1.3", "Python 의존성 설치 (RPi.GPIO, picamera2 등)", "import 오류 없음"),
  row("1.4", "Head: install_head_services.sh 실행", "유닛 enable(자동시작 등록), 즉시 start는 하지 않음"),
  row("1.5", "Node1/2/3: install_nodeN_services.sh 실행", "각 노드 유닛 enable 완료"),
  row("1.6", "station_map.conf에 실제 station MAC 기입 (Head 로컬 전용, 커밋 금지)", "Node1/2/3 MAC→IP 매핑 채워짐"),
]));
c.push(Spacer());

// ---- 2. 최초 AP ----
c.push(H1("2. 최초 AP 기동"));
c.push(Callout("SSH 끊김 경고", [
  [{ t: "wlan0로 SSH 접속 중 start_ap.sh를 실행하면 연결이 끊깁니다. 유선/별도 경로 또는 콘솔에서 실행하고, 복구는 stop_ap.sh로 기존 연결(netplan-wlan0-ssing)을 되살립니다.", b: false }],
], "warn"));
c.push(makeTable(W, [
  headRow,
  row("2.1", "Head에서 start_ap.sh --yes 실행", "wlan0에 192.168.4.1/24 할당, hostapd·dnsmasq 기동"),
  row("2.2", "SSID HANSEL_HEAD_AP 가 주변 기기에서 검색됨", "SSID 노출 (채널 6)"),
  row("2.3", "PC가 HANSEL_HEAD_AP에 접속", "DHCP로 192.168.4.100~150 범위 IP 수신"),
  row("2.4", "Head로 ping 192.168.4.1 성공", "응답 정상"),
  row("2.5", "(실패 시) stop_ap.sh로 기존 Wi-Fi 복구", "netplan-wlan0-ssing 연결 복귀"),
]));
c.push(Spacer());

// ---- 3. AP 전환 후 재접속 ----
c.push(H1("3. AP 전환 후 재접속"));
c.push(makeTable(W, [
  headRow,
  row("3.1", "PC: HANSEL_HEAD_AP 접속 후 Head/Node ping", "192.168.4.1/.11/.12/.13 모두 응답"),
  row("3.2", "Node1/2/3: setup_static_ip.sh 적용 후 AP 자동 접속", "각 노드 .11/.12/.13 고정 IP로 접속"),
  row("3.3", "Android 단말: HANSEL_HEAD_AP 수동 접속", "192.168.4.20 (또는 지정 IP) 수신/설정"),
  row("3.4", "Head에서 각 노드·Android로 ping", "전 구간 응답"),
]));
c.push(Spacer());

// ---- 4. 2차 부팅 자동 기동 ----
c.push(H1("4. 2차 부팅 이후 자동 기동"));
c.push(makeTable(W, [
  headRow,
  row("4.1", "Head 재부팅 후 hansel-ap.service 자동 기동", "AP가 사람 개입 없이 올라옴"),
  row("4.2", "hansel-head-control / -camera / -monitor 자동 기동", "After=hansel-ap 순서로 active"),
  row("4.3", "Node1/2/3 재부팅 후 고정 IP로 AP 자동 재접속", "노드가 .11/.12/.13로 재연결"),
  row("4.4", "hansel-nodeN-control / -relay 자동 기동", "network-online 이후 active"),
  row("4.5", "Android는 수동 재접속 필요 확인", "수동 접속 후 동작"),
  row("4.6", "최소 부팅 점검 (systemctl status 핵심 유닛)", "모두 active, 실패 유닛 없음"),
]));
c.push(Spacer());

// ---- 5. 주행 명령 ----
c.push(H1("5. 주행 명령 수신"));
c.push(makeTable(W, [
  headRow,
  row("5.1", "PC keyboard.py 환경변수 IP를 192.168.4.x로 지정", "HEAD_IP/NODE_IP가 AP 대역으로 설정"),
  row("5.2", "Head 주행 명령(UDP 5000) 송신 → 모터 반응", "Head 전/후/좌/우 동작"),
  row("5.3", "Node1/2/3 주행 명령(UDP 5000) 송신 → 모터 반응", "각 노드 개별 동작"),
  row("5.4", "Head 제어 프로세스 기동 (check_duplicate_pins 통과)", "RuntimeError 없이 기동 — GPIO 중복 없음"),
  row("5.5", "헤드 서보(GPIO17) + 앞 DC모터(GPIO12) 동시 구동", "서보·앞모터 모두 정상 동작"),
]));
c.push(Callout("GPIO12 충돌 해소 확인 (최신 코드 기준)", [
  [{ t: "이전 HEAD_SERVO_PIN/FRONT_ENA_PIN(GPIO12) 충돌은 커밋 351a1bf에서 HEAD_SERVO_PIN을 GPIO17(물리 11)로 이동하여 해소되었습니다.", b: false }],
  [{ t: "최신 코드 기준 충돌 해소 확인, 실물 구동 검증 필요 — 현장에서 헤드 서보와 앞 DC모터가 동시에 정상 동작하는지 확인하세요.", b: true, color: "C00000" }],
], "ok"));
c.push(Spacer());

// ---- 6. 영상 릴레이 ----
c.push(H1("6. 영상 릴레이 (Head→Node1→Node2→Node3→Android)"));
c.push(P([{ t: "전송 경로(UDP 5001, raw H.264): Head 카메라 → Node1 → Node2 → Node3 → Android. 각 홉은 byte-for-byte 포워딩입니다. ", b: false },
  { t: "실물 영상 수신은 미검증 — 반드시 현장 확인.", b: true, color: "C00000" }]));
c.push(makeTable(W, [
  headRow,
  row("6.1", "Head: run_camera_stream.sh 로 H.264 송신 (→192.168.4.11:5001)", "패킷 송신 시작"),
  row("6.2", "Node1: udp_h264_relay 수신·포워딩 (→.12:5001)", "수신/송신 카운트 증가"),
  row("6.3", "Node2: 릴레이 (→.13:5001)", "포워딩 정상"),
  row("6.4", "Node3: 릴레이 (→Android .20:5001)", "포워딩 정상"),
  row("6.5", "Android: 영상 디코드·표시", "실시간 화면 표시 (지연/끊김 기록)"),
]));
c.push(Spacer());

// ---- 7. RSSI 통신 ----
c.push(H1("7. RSSI 통신 / 텔레메트리"));
c.push(P([{ t: "RSSI 실험 스크립트 포트: 텔레메트리 UDP 5051, 명령 UDP 5052, 파일 TCP 5053. ", b: false },
  { t: "systemd 미등록(수동 실행), 실험용.", b: true }]));
c.push(makeTable(W, [
  headRow,
  row("7.1", "각 Pi에서 RSSI 측정값 수집 (iw station dump 기반)", "station별 signal 값 출력"),
  row("7.2", "텔레메트리(UDP 5051) 송수신", "수신측에서 값 표시"),
  row("7.3", "rssi_monitor 표시/로깅", "EWMA 필터링 값 갱신"),
]));
c.push(Spacer());

// ---- 8. 자동 분리 ----
c.push(H1("8. 자동 분리 (RSSI → 가드 → 분리 서보)"));
c.push(P([{ t: "파이프라인: RSSI 약화 → link_guard 연속 카운트(degraded 10) → station_map MAC→IP → UDP detach_press(5000) → 분리 서보(GPIO6). 또는 PC keyboard.py가 가드 메시지(UDP 6000)를 받아 분리. ", b: false },
  { t: "실물 자동 분리 미검증 — 반드시 현장 확인.", b: true, color: "C00000" }]));
c.push(makeTable(W, [
  headRow,
  row("8.1", "station_map.conf 실제 MAC 매핑 적용 확인", "Node MAC→IP 정상 매핑"),
  row("8.2", "RSSI 임계(-70 dBm) 이하로 떨어뜨림 (거리 확보)", "link_watch가 degraded 감지"),
  row("8.3", "degraded 연속 10회 → detach_bridge 트리거", "해당 Node IP:5000으로 detach_press 송신"),
  row("8.4", "분리 서보(GPIO6) 동작 → 물리 분리", "체결 해제 확인"),
  row("8.5", "분리 래치 동작 (1회만, /var/lib/hansel/detach_state.json)", "중복 분리 안 함; 재시험 시 reset_detach_state.sh"),
  row("8.6", "(대체 경로) PC가 가드 메시지(UDP 6000) 수신 → 분리·다음 유닛 비활성", "keyboard.py 동작 확인"),
  row("8.7", "(신규 라우터) 통신부→HEAD:6000→head_detach_router→actor:5000", "라우터가 액추에이터 유닛에 detach_press 송신"),
  row("8.8", "액추에이터 매핑 확인 (NODE1→Head, NODE2→Node1, NODE3→Node2 서보)", "앞 유닛 서보가 체결 해제"),
]));
c.push(Callout("신규 detach 라우터 (커밋 351a1bf)", [
  [{ t: "통신부가 각 Node로 직접 보내지 않고 HEAD_IP:6000(head_detach_router.py)로 detach 요청을 보내면, 라우터가 액추에이터 유닛의 제어서버(UDP 5000)로 detach_press를 분배합니다. 매핑: NODE1 분리→Head 서보, NODE2 분리→Node1 서보, NODE3 분리→Node2 서보.", b: false }],
  [{ t: "기본 IP가 임시 SSH(10.180.86.x)이므로 AP 운용 시 HEAD_IP/NODE*_IP 환경변수를 192.168.4.x로 지정해야 합니다. systemd 미등록(수동 실행) — 실물 검증 필요.", b: false }],
], "warn"));
c.push(Spacer());

c.push(Rule());
c.push(P([{ t: "전체 결과 요약: ", b: true }, { t: "성공 ___ / 실패 ___ / 보류 ___ . 미검증 핵심 항목(영상 릴레이·자동 분리·헤드 서보 구동)을 우선 처리하세요." }]));

build("deliverables/HANSEL_GRETEL_FIELD_TEST_CHECKLIST.docx", "HANSEL/GRETEL 현장 시험 체크리스트 (DRAFT)", c)
  .then(() => console.log("OK checklist docx"))
  .catch(e => { console.error(e); process.exit(1); });

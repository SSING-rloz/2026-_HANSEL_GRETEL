const h = require("./helpers.js");
const { H1, H2, H3, P, Bullet, NumItem, Spacer, Rule, Code, CodeBlock, makeTable, Callout, TitlePage, build, TableOfContents, Paragraph, TextRun, PageBreak } = h;

const c = [];

// ---------- Title page ----------
TitlePage({
  title: ["HANSEL / GRETEL", "배포 및 운영 문서"],
  subtitle: "Deployment & Operation Guide",
  banner: [
    [{ t: "DRAFT — 최신 코드 기준 작성, 실물 end-to-end 검증 전", b: true, color: "843C0C" }],
    [{ t: "코드(origin/main) 검증 완료 · 실기기 통합 동작은 미검증", color: "843C0C" }],
  ],
  bannerKind: "warn",
  meta: [
    "대상: Raspberry Pi 4 (Debian GNU/Linux 13 trixie) · Android 수신기 · Controller PC",
    "기준 커밋: origin/main 351a1bf (\"헤드가 명령 받고 node들에 detach 명령 분배\") 반영",
    "작성일: 2026-05-30",
  ],
}).forEach(x => c.push(x));

// ---------- TOC ----------
c.push(H1("목차"));
c.push(new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }));
c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 1. 시스템 개요 ----------
c.push(H1("1. 시스템 개요"));
c.push(P([
  { t: "HANSEL/GRETEL은 1대의 Head와 3대의 Node로 구성된 분리형(detachable) 군집 로봇입니다. " },
  { t: "Head Pi가 Wi-Fi AP를 호스팅하고, 모든 Node와 Android 수신기가 이 AP에 접속합니다. " },
  { t: "Head는 CSI 카메라 영상을 H.264로 인코딩해 Node 체인을 거쳐 Android로 릴레이하고, " },
  { t: "Controller PC(또는 Head 자동분리 브리지)가 UDP로 각 유닛에 주행/서보/분리 명령을 보냅니다." },
]));
c.push(P([
  { t: "RSSI(신호세기) 저하가 지속되면 해당 Node를 물리적으로 분리(detach servo)하여 ", },
  { t: "통신 범위를 벗어나는 Node를 떼어내는 자동분리 기능을 갖습니다.", b: true },
]));

c.push(H2("1-1. 구성 요소와 역할"));
c.push(makeTable([1500, 3100, 4760], [
  ["유닛", "역할", "주요 프로세스 / 포트"],
  ["Head Pi", "Wi-Fi AP 호스트, 카메라 영상 송출, 주행/서보/분리 제어, RSSI 모니터 + 자동분리 브리지", [{ t: "start_ap.sh, Head_control.py(UDP 5000), head_h264_sender.py(UDP 5001), run_guard_detach.sh", code: true }]],
  ["Node1", "주행/엔코더 PID + 분리 서보, 영상 릴레이(→Node2)", [{ t: "Node1_control.py(UDP 5000), udp_h264_relay.py(UDP 5001)", code: true }]],
  ["Node2", "주행/엔코더 PID + 분리 서보, 영상 릴레이(→Node3)", [{ t: "Node2_control.py(UDP 5000), udp_h264_relay.py(UDP 5001)", code: true }]],
  ["Node3", "주행/엔코더 PID + 분리 서보, 영상 릴레이(→Android)", [{ t: "Node3_control.py(UDP 5000), udp_h264_relay.py(UDP 5001)", code: true }]],
  ["Android", "영상 수신/표시 (H.264 Annex-B 재조립)", [{ t: "android/ 앱, UDP 5001 수신", code: true }]],
  ["Controller PC", "키보드 주행 제어 + RSSI guard 상태 수신", [{ t: "controller/desktop/keyboard.py (송신 UDP 5000, 수신 UDP 6000)", code: true }]],
]));

c.push(Spacer());
c.push(H2("1-2. 전체 구성도와 데이터 흐름"));
c.push(P([{ t: "Wi-Fi AP: ", b: true }, { t: "HANSEL_HEAD_AP (192.168.4.0/24, 채널 6, WPA2-PSK)", code: true }]));
CodeBlock([
  "                    [ HANSEL_HEAD_AP  192.168.4.0/24 ]",
  "                               |",
  "   Controller PC ──UDP 5000(text cmd)──► Head / Node 제어 서버",
  "   (keyboard.py)  ◄─UDP 6000(guard)──── 통신부 RSSI 모듈(옵션)",
  "",
  "   영상 체인 (raw H.264 Annex-B / UDP 5001, RTP 아님):",
  "   Head .1 ──5001──► Node1 .11 ──5001──► Node2 .12 ──5001──►",
  "                                    Node3 .13 ──5001──► Android .20",
  "",
  "   자동분리 (Head 내부):",
  "   iw station dump → EWMA → 임계 → guard → detach_bridge",
  "        └─UDP 5000 \"detach_press\"─► 대상 Node 제어 서버",
]).forEach(x => c.push(x));

c.push(Callout("데이터 평면 요약", [
  [{ t: "제어 평면: ", b: true }, { t: "UDP 5000 (텍스트 명령). 주행·서보·detach_press 모두 동일 포트." }],
  [{ t: "영상 평면: ", b: true }, { t: "UDP 5001 (raw H.264). Head→Node1→Node2→Node3→Android 단방향 릴레이." }],
  [{ t: "감시 평면: ", b: true }, { t: "Head 내부 RSSI 파이프라인 → 자동분리. Controller는 UDP 6000으로 guard 상태 수신(옵션)." }],
], "ok"));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 2. 네트워크 / IP 정책 ----------
c.push(H1("2. 네트워크 / IP 정책"));
c.push(P("운영 IP는 고정 정책을 사용합니다. 핵심 유닛은 정적 IP를, 임시 클라이언트(PC/실험 기기)는 DHCP 동적 풀을 사용합니다."));

c.push(H2("2-1. 정적 IP 표 (운영)"));
c.push(makeTable([2100, 2400, 2400, 2460], [
  ["유닛", "IP 주소", "할당 방식", "설정 위치"],
  ["Head Pi (AP)", [{ t: "192.168.4.1/24", code: true }], "정적 (AP 게이트웨이)", [{ t: "ap/start_ap.sh", code: true }]],
  ["Node1", [{ t: "192.168.4.11", code: true }], "정적 (NetworkManager)", [{ t: "node1/net/setup_static_ip.sh", code: true }]],
  ["Node2", [{ t: "192.168.4.12", code: true }], "정적 (NetworkManager)", [{ t: "node2/net/setup_static_ip.sh", code: true }]],
  ["Node3", [{ t: "192.168.4.13", code: true }], "정적 (NetworkManager)", [{ t: "node3/net/setup_static_ip.sh", code: true }]],
  ["Android", [{ t: "192.168.4.20", code: true }], "정적 (폰에서 수동 설정)", "Wi-Fi 고정 IP 수동 입력"],
]));
c.push(P([{ t: "게이트웨이/DNS: ", b: true }, { t: "192.168.4.1 (Head Pi). NAT는 현 단계에서 미설정 → 인터넷 경유 없음.", code: false }]));

c.push(H2("2-2. DHCP 동적 할당"));
c.push(makeTable([3200, 3000, 3160], [
  ["항목", "값", "근거"],
  ["동적 풀 범위", [{ t: "192.168.4.100 ~ 192.168.4.150", code: true }], [{ t: "ap/dnsmasq.conf", code: true }]],
  ["임대 시간", "12h", [{ t: "dhcp-range … 12h", code: true }]],
  ["동적 할당 대상", "AP에 붙는 임시 PC/실험 기기 등 (정적 미지정 클라이언트)", "dnsmasq 자동 배정"],
  ["정적 vs 동적 경계", "정적 .1/.11/.12/.13/.20은 풀(.100–.150) 밖 → 충돌 없음", "dnsmasq.conf 주석 정책"],
]));
c.push(Callout("주의: start_ap.sh 로그의 stale 텍스트", [
  [{ t: "ap/start_ap.sh 의 마지막 요약 echo는 여전히 ", }, { t: "\"DHCP: 192.168.4.10 - 192.168.4.50\"", code: true }, { t: " 라고 출력합니다." }],
  [{ t: "이는 화면 출력용 문구일 뿐이며, 실제 권위 있는 범위는 dnsmasq.conf의 ", }, { t: ".100–.150", code: true }, { t: " 입니다. 혼동 주의(코드 정리 권장)." }],
], "warn"));

c.push(H2("2-3. 정적/동적 설정 스크립트"));
c.push(Bullet([{ t: "Head AP 주소(.1): ", b: true }, { t: "ap/start_ap.sh", code: true }, { t: " 가 wlan0에 직접 할당 (DHCP 아님)." }]));
c.push(Bullet([{ t: "Node 정적 IP: ", b: true }, { t: "nodeN/net/setup_static_ip.sh --yes", code: true }, { t: " 가 nmcli 프로필(ipv4.method manual)로 설정. autoconnect=yes." }]));
c.push(Bullet([{ t: "Android: ", b: true }, { t: "폰 Wi-Fi 설정에서 192.168.4.20 고정 IP를 수동 입력 (dnsmasq 예약 아님)." }]));

c.push(H2("2-4. station_map.conf 와 자동분리의 관계"));
c.push(P([
  { t: "자동분리 브리지(detach_bridge.py)는 RSSI가 저하된 station의 ", },
  { t: "wlan0 MAC", b: true },
  { t: "을 ", },
  { t: "monitor/station_map.conf", code: true },
  { t: " 에서 조회해 대상 Node IP로 변환합니다." },
]));
c.push(Callout("실기기 필수 작업", [
  [{ t: "현재 station_map.conf 에는 실제 MAC이 없고 주석 예시만 있습니다. ", b: true }],
  [{ t: "실제 Node wlan0 MAC을 채우기 전에는 detach_bridge.py가 ", }, { t: "unknown_station … action=skip", code: true }, { t: " 로그만 남기고 분리를 수행하지 않습니다." }],
  [{ t: "실제 MAC 매핑값은 보안상 비공개 문서(PRIVATE_DEVICE_CONFIG)에 있으며, Head Pi 로컬에서만 반영합니다(저장소 커밋 금지)." }],
], "warn"));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 3. 포트맵 ----------
c.push(H1("3. 포트맵 (Live 포트)"));
c.push(P("아래는 최신 origin/main 코드에서 확인된 포트입니다. \"실물 검증\" 열은 코드 구조 확인과 실기기 통신 성공을 구분합니다."));
c.push(makeTable([1500, 900, 1850, 1850, 1860, 1400], [
  ["기능", "포트", "Sender", "Receiver/Listener", "근거 파일", "실물 검증"],
  [[{ t: "구동/서보/분리 명령", b: true }], [{ t: "UDP 5000", code: true }], [{ t: "keyboard.py / detach_bridge.py", code: true }], [{ t: "Head/Node*_control.py (0.0.0.0:5000)", code: true }], [{ t: "*_control.py PORT=5000", code: true }], [{ t: "필요", color: "C00000" }]],
  [[{ t: "detach command", }], [{ t: "UDP 5000", code: true }], [{ t: "detach_bridge.py", code: true }], [{ t: "대상 Node*_control.py", code: true }], [{ t: "detach_bridge.py --control-port 5000", code: true }], [{ t: "필요", color: "C00000" }]],
  [[{ t: "영상 H.264 릴레이", b: true }], [{ t: "UDP 5001", code: true }], [{ t: "head_h264_sender.py / udp_h264_relay.py", code: true }], [{ t: "Node relay / Android", code: true }], [{ t: "VIDEO_PORT / RELAY_*_PORT=5001", code: true }], [{ t: "필요", color: "C00000" }]],
  [[{ t: "detach 요청 (신규 라우터)", b: true }], [{ t: "UDP 6000", code: true }], [{ t: "rssi_to_head_detach_sender.py (통신부)", code: true }], [{ t: "head_detach_router.py (Head 0.0.0.0:6000)", code: true }], [{ t: "DETACH_ROUTER_PORT=6000", code: true }], [{ t: "필요", color: "C00000" }]],
  [[{ t: "RSSI guard 상태", }], [{ t: "UDP 6000", code: true }], [{ t: "통신부 RSSI 모듈 (외부)", code: true }], [{ t: "keyboard.py GUARD_PORT", code: true }], [{ t: "keyboard.py GUARD_PORT=6000", code: true }], [{ t: "필요", color: "C00000" }]],
  [[{ t: "RSSI 실험 telemetry", }], [{ t: "UDP 5051", code: true }], [{ t: "하류 이웃 Pi", code: true }], [{ t: "상류 이웃 Pi", code: true }], [{ t: "*_rssi_listen.py TELEM_PORT", code: true }], [{ t: "실험용", color: "7030A0" }]],
  [[{ t: "RSSI 실험 command", }], [{ t: "UDP 5052", code: true }], [{ t: "상류 → 하류", code: true }], [{ t: "이웃 Pi", code: true }], [{ t: "*_rssi_listen.py CMD_PORT", code: true }], [{ t: "실험용", color: "7030A0" }]],
  [[{ t: "RSSI 실험 CSV file", }], [{ t: "TCP 5053", code: true }], [{ t: "하류 → 상류", code: true }], [{ t: "rssi_monitor.py / 이웃", code: true }], [{ t: "*_rssi_listen.py FILE_PORT", code: true }], [{ t: "실험용", color: "7030A0" }]],
]));

c.push(Callout("포트 관련 정정 사항 (이전 초안 대비)", [
  [{ t: "RSSI 실험 포트는 5051/5052/5053 입니다. ", b: true }, { t: "이전 초안의 6001/6002/6003은 최신 코드와 불일치하므로 폐기합니다." }],
  [{ t: "UDP 5005는 최신 live 코드 어디에도 존재하지 않습니다", b: true }, { t: " (stale 주석조차 없음). rssi_monitor/vid_quality_fps_logger.py 의 ", }, { t: "udp://@0.0.0.0:5000", code: true }, { t: " 은 별도 FFmpeg 화질 로거의 예시 입력일 뿐, live 제어 5000과 무관합니다." }],
  [{ t: "systemd 자동 시작 대상: ", b: true }, { t: "UDP 5000(control) · UDP 5001(camera/relay)만 부팅 서비스. 6000/5051/5052/5053은 수동·실험용." }],
], "warn"));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 4. 영상 relay ----------
c.push(H1("4. 영상 Relay 구조"));
c.push(H2("4-1. 실행 파일 및 경로"));
c.push(makeTable([1700, 4100, 3560], [
  ["역할", "실행 파일", "비고"],
  ["Head 송신", [{ t: "head/camera/head_h264_sender.py (run_camera_stream.sh)", code: true }], "Picamera2 → H264 → UDP 청크(1280×720@30, ~1Mbps, mtu 1200)"],
  ["Node1 릴레이", [{ t: "node1/video/udp_h264_relay.py", code: true }], "byte-for-byte UDP 전달 (RTP/파싱 없음)"],
  ["Node2 릴레이", [{ t: "node2/video/udp_h264_relay.py", code: true }], "동일"],
  ["Node3 릴레이", [{ t: "node3/video/udp_h264_relay.py", code: true }], "최종 hop → Android"],
  ["Android 수신", [{ t: "android/ 앱", code: true }], "바이트 누적 + Annex-B start code 재분할"],
]));
c.push(Callout("빈 스텁 파일 주의 (live 경로 아님)", [
  [{ t: "head/video/sender.sh, head/video/relay.sh, head/video/receiver.md, control/command_server.py, control/detach_trigger.sh 는 모두 빈 파일(스텁)입니다.", }],
  [{ t: "실제 live 영상 경로는 camera/head_h264_sender.py(Head) + video/udp_h264_relay.py(Node) 입니다.", b: true }],
], "warn"));

c.push(H2("4-2. hop별 송수신 (환경변수 기준)"));
c.push(makeTable([1600, 2400, 2400, 2960], [
  ["Hop", "수신(listen)", "송신 대상", "환경변수 근거"],
  ["Head → Node1", "—", [{ t: "192.168.4.11:5001", code: true }], [{ t: "hansel-head.env VIDEO_FIRST_HOP_IP", code: true }]],
  ["Node1 → Node2", [{ t: "0.0.0.0:5001", code: true }], [{ t: "192.168.4.12:5001", code: true }], [{ t: "hansel-node1.env RELAY_DST_IP", code: true }]],
  ["Node2 → Node3", [{ t: "0.0.0.0:5001", code: true }], [{ t: "192.168.4.13:5001", code: true }], [{ t: "hansel-node2.env RELAY_DST_IP", code: true }]],
  ["Node3 → Android", [{ t: "0.0.0.0:5001", code: true }], [{ t: "192.168.4.20:5001", code: true }], [{ t: "hansel-node3.env RELAY_DST_IP", code: true }]],
]));
c.push(P([{ t: "부팅 자동 시작: ", b: true }, { t: "Head는 hansel-head-camera.service, Node는 hansel-nodeN-relay.service 로 자동 기동(설치·enable 후)." }]));
c.push(Callout("검증 상태", [
  [{ t: "코드상 연결 구조: 확인됨", b: true, color: "375623" }, { t: " (체인/포트/환경변수 일치)." }],
  [{ t: "실기기 end-to-end 영상 relay 성공: 미검증 → ", }, { t: "실물 검증 필요", b: true, color: "C00000" }, { t: ". Android 수신 표시까지 확인 전에는 \"동작\"으로 단정하지 않습니다." }],
], "warn"));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 5. AP 및 부팅 실행 방식 ----------
c.push(H1("5. AP 및 부팅 실행 방식"));

c.push(H2("5-A. 최초 설치 / 첫 부팅 준비 (새로 포맷한 Pi)"));
c.push(NumItem([{ t: "git 설치 및 저장소 clone: ", b: true }, { t: "sudo apt install -y git && git clone <repo>", code: true }], "steps"));
c.push(NumItem([{ t: "의존성 설치: ", b: true }, { t: "python3, RPi.GPIO, picamera2(Head), hostapd, dnsmasq, iw, NetworkManager(nmcli)", code: true }], "steps"));
c.push(NumItem([{ t: "systemd 유닛 설치/enable: ", b: true }, { t: "Head → sudo ./systemd/install_head_services.sh --yes ; Node → sudo ./systemd/install_nodeN_services.sh --yes", code: true }, { t: " (enable만, AP는 start 안 함)" }], "steps"));
c.push(NumItem([{ t: "Node 정적 IP 적용: ", b: true }, { t: "sudo bash net/setup_static_ip.sh --yes", code: true }, { t: " (wlan0가 HANSEL_HEAD_AP에 정적 접속)" }], "steps"));
c.push(NumItem([{ t: "Head 로컬 전용 설정: ", b: true }, { t: "monitor/station_map.conf 에 실제 Node MAC 반영 (비공개 문서 참조, 커밋 금지)" }], "steps"));
c.push(NumItem([{ t: "최초 AP 기동: ", b: true }, { t: "sudo systemctl start hansel-ap.service", code: true }, { t: " (또는 sudo bash ap/start_ap.sh --yes)" }], "steps"));
c.push(Callout("⚠ SSH 끊김 경고 및 복구 준비", [
  [{ t: "start_ap.sh 는 wlan0를 Wi-Fi 클라이언트 → AP 모드로 전환합니다. 현재 wlan0 Wi-Fi로 SSH 중이면 세션이 끊깁니다.", b: true }],
  [{ t: "최초 AP 기동 전에 콘솔/키보드·모니터 직접 접속 또는 유선 복구 경로를 준비하세요." }],
  [{ t: "복구: 콘솔에서 ", }, { t: "sudo bash ap/stop_ap.sh --yes", code: true }, { t: " (이전 Wi-Fi 연결 netplan-wlan0-ssing 으로 복귀)." }],
]));
c.push(P([{ t: "AP 성공 기준: ", b: true }, { t: "SSID HANSEL_HEAD_AP 가 보이고, wlan0=192.168.4.1, Node/PC가 접속·DHCP 또는 정적 join 성공, hostapd/dnsmasq active." }]));

c.push(H2("5-B. 설치 완료 후 두 번째 부팅부터"));
c.push(makeTable([3400, 5960], [
  ["동작", "설명"],
  ["Head AP 자동 기동", [{ t: "hansel-ap.service 가 enable 되어 ", }, { t: "매 부팅 시 자동으로 start_ap.sh 실행 → AP 자동 상승", b: true }, { t: " (최초 설치 시에만 수동 start 필요)." }]],
  ["Head 제어/영상/모니터", "hansel-head-control / -camera / -monitor 자동 시작 (After=hansel-ap)"],
  ["Node AP 재접속", [{ t: "autoconnect=yes 프로필로 wlan0가 HANSEL_HEAD_AP에 ", }, { t: "자동 재접속", b: true }, { t: "; control/relay 서비스 자동 시작" }]],
  ["Android", [{ t: "수동", b: true }, { t: ": 폰 Wi-Fi로 HANSEL_HEAD_AP 접속 + 수신 앱 실행 필요" }]],
]));
c.push(H3("부팅 후 최소 점검 명령"));
CodeBlock([
  "# Head",
  "systemctl status hansel-ap.service hansel-head-control.service",
  "ip addr show wlan0            # 192.168.4.1 확인",
  "iw dev wlan0 station dump     # 접속한 Node MAC/신호 확인",
  "journalctl -u hansel-head-camera.service -f",
  "# Node",
  "systemctl status hansel-node1-control.service hansel-node1-relay.service",
  "ping -c2 192.168.4.1          # AP 도달 확인",
]).forEach(x => c.push(x));

c.push(H3("종료 / 재시작 / 장애 복구"));
c.push(Bullet([{ t: "AP 중단·복구: ", b: true }, { t: "sudo systemctl stop hansel-ap.service", code: true }, { t: " 또는 ", }, { t: "sudo bash ap/stop_ap.sh --yes", code: true }]));
c.push(Bullet([{ t: "서비스 재시작: ", b: true }, { t: "sudo systemctl restart hansel-<unit>", code: true }]));
c.push(Bullet([{ t: "프로세스 강제 종료: ", b: true }, { t: "sudo pkill -f Head_control.py / udp_h264_relay.py", code: true }]));
c.push(Bullet([{ t: "분리 latch 초기화(미션 전): ", b: true }, { t: "sudo bash monitor/reset_detach_state.sh --yes && sudo systemctl restart hansel-head-monitor", code: true }]));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 6. 자동분리 ----------
c.push(H1("6. 자동분리(Auto-detach) 구조"));
c.push(H2("6-1. 실행 흐름 (Head 내부)"));
CodeBlock([
  "rssi_reader.sh   iw dev wlan0 station dump → station=<MAC> signal_dbm=<v>",
  "      │",
  "link_filter.py   EWMA 평활 (alpha=0.3)",
  "      │",
  "link_watch.py    임계 비교 (threshold=-70dBm) → link_degraded / link_ok",
  "      │",
  "link_guard.py    연속 카운트 (degraded=10, recover=6, interval=0.2s)",
  "      │          → guard_status=detach_candidate / recovered / watching",
  "      ▼",
  "detach_bridge.py station_map.conf(MAC→IP) 조회",
  "      └─ UDP \"detach_press\" → 대상 Node 제어서버 :5000  (latch 후 1회)",
]).forEach(x => c.push(x));
c.push(P([{ t: "통합 러너: ", b: true }, { t: "run_guard_detach.sh = run_monitor.sh(파이프라인) | detach_bridge.py", code: true }, { t: ". systemd ", }, { t: "hansel-head-monitor.service", code: true }, { t: " 로 부팅 자동 시작." }]));

c.push(H2("6-2. Node 식별 / MAC"));
c.push(Bullet([{ t: "분리 대상 식별자 = 저하된 station의 wlan0 MAC. ", }, { t: "station_map.conf", code: true }, { t: " 에서 MAC→(IP, 이름)으로 매핑." }]));
c.push(Bullet([{ t: "실제 MAC은 Head Pi 로컬에서만 ", }, { t: "station_map.conf", code: true }, { t: " 에 기입(저장소 커밋 금지). 비공개 문서에 매핑값 수록." }]));

c.push(H2("6-3. Latch 정책"));
c.push(Bullet([{ t: "한 미션당 Node 1회만 분리. ", b: true }, { t: "상태는 ", }, { t: "/var/lib/hansel/detach_state.json", code: true }, { t: " 에 영속 → 재시작/재부팅에도 재분리 안 함." }]));
c.push(Bullet([{ t: "RSSI가 잠시 회복(recovered)해도 재무장 안 함. ", }, { t: "reset_detach_state.sh --yes", code: true }, { t: " (미션 전 수동)로만 해제." }]));

c.push(H2("6-4. 병렬 경로: Controller(keyboard.py)"));
c.push(P([
  { t: "Head 내부 브리지와 ", }, { t: "별개로", b: true },
  { t: ", Controller의 keyboard.py 도 UDP 6000에서 통신부 guard 메시지(예 ", },
  { t: "\"NODE1,detach_candidate\"", code: true },
  { t: ")를 받아 해당 유닛에 detach를 보내고 다음 유닛 주행을 비활성화하는 별도 자동분리 경로를 갖습니다." },
]));
c.push(H2("6-5. 신규 경로: Head 중앙 detach 라우터 (커밋 351a1bf)"));
c.push(P([
  { t: "최신 커밋에서 ", }, { t: "통신부 → Head 라우터 → 액추에이터 유닛", b: true },
  { t: " 의 중앙집중 detach 분배 경로가 추가되었습니다." },
]));
CodeBlock([
  "통신부 RSSI 판단",
  "  └ rssi_to_head_detach_sender.py  request_detach_from_head(\"NODE2\")",
  "        └─ UDP → HEAD_IP:6000",
  "head_detach_router.py (Head Pi, listen UDP 6000)",
  "        └─ 액추에이터 결정 → UDP \"detach_press\" → actor_ip:5000 (3회 반복)",
]).forEach(x => c.push(x));
c.push(P([{ t: "기구 매핑(액추에이터): ", b: true }, { t: "NODE1 분리→Head 서보, NODE2 분리→Node1 서보, NODE3 분리→Node2 서보. " }, { t: "분리 대상이 아니라 앞 유닛의 서보가 체결을 푼다는 점에 주의.", b: true }]));
c.push(Bullet([{ t: "라우터 listen 포트: ", }, { t: "UDP 6000", code: true }, { t: " (DETACH_ROUTER_PORT). 제어 송신: ", }, { t: "UDP 5000", code: true }, { t: " (ROBOT_CONTROL_PORT)." }]));
c.push(Bullet([{ t: "기본 IP는 임시 SSH(10.180.86.x) → AP 운용 시 ", }, { t: "HEAD_IP/NODE*_IP", code: true }, { t: " 환경변수를 192.168.4.x로 지정해야 함." }]));
c.push(Bullet([{ t: "동일 target 반복 분리 방지: ", }, { t: "ONE_SHOT_PER_TARGET=1", code: true }, { t: ", 쿨다운 3600s." }]));
c.push(Bullet([{ t: "systemd 미등록(현재 수동 실행). 부팅 자동 시작 대상 아님 — ", }, { t: "실물 검증 필요.", b: true, color: "C00000" }]));
c.push(Callout("검증 상태 — 자동분리", [
  [{ t: "코드 흐름: 확인됨", b: true, color: "375623" }, { t: " (RSSI→guard→bridge→UDP 5000→detach servo, 그리고 통신부→Head 라우터(6000)→actor:5000)." }],
  [{ t: "실기기 자동분리 성공: 미검증 → ", }, { t: "실물 검증 필요", b: true, color: "C00000" }, { t: ". station_map.conf 실제 MAC 반영 및 라우터 기동 후에야 동작합니다." }],
], "warn"));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 7. GPIO 핀 표 ----------
c.push(H1("7. GPIO 핀 표 (최신 코드)"));
c.push(H2("7-1. Head Pi (Head_control.py)"));
c.push(makeTable([3000, 1900, 1900, 2560], [
  ["기능", "BCM GPIO", "물리 핀", "상수명"],
  ["메인 좌 모터 PWM (ENA)", "18", "12", [{ t: "ENA_PIN", code: true }]],
  ["메인 좌 모터 IN1", "23", "16", [{ t: "IN1_PIN", code: true }]],
  ["메인 좌 모터 IN2", "24", "18", [{ t: "IN2_PIN", code: true }]],
  ["메인 우 모터 PWM (ENB)", "13", "33", [{ t: "ENB_PIN", code: true }]],
  ["메인 우 모터 IN3", "27", "13", [{ t: "IN3_PIN", code: true }]],
  ["메인 우 모터 IN4", "22", "15", [{ t: "IN4_PIN", code: true }]],
  ["앞 DC모터 L ENA", "12", "32", [{ t: "FRONT_ENA_PIN", code: true }]],
  ["앞 DC모터 L IN1", "4", "7", [{ t: "FRONT_IN1_PIN", code: true }]],
  ["앞 DC모터 L IN2", "25", "22", [{ t: "FRONT_IN2_PIN", code: true }]],
  ["앞 DC모터 R ENB", "19", "35", [{ t: "FRONT_ENB_PIN", code: true }]],
  ["앞 DC모터 R IN3", "5", "29", [{ t: "FRONT_IN3_PIN", code: true }]],
  ["앞 DC모터 R IN4", "7", "26", [{ t: "FRONT_IN4_PIN", code: true }]],
  ["좌 엔코더 A", "20", "38", [{ t: "LEFT_ENC_A", code: true }]],
  ["좌 엔코더 B", "21", "40", [{ t: "LEFT_ENC_B", code: true }]],
  ["우 엔코더 A", "16", "36", [{ t: "RIGHT_ENC_A", code: true }]],
  ["우 엔코더 B", "26", "37", [{ t: "RIGHT_ENC_B", code: true }]],
  ["헤드 서보", "17", "11", [{ t: "HEAD_SERVO_PIN", code: true }]],
  ["분리 서보", "6", "31", [{ t: "DETACH_SERVO_PIN", code: true }]],
]));
c.push(Callout("핀 충돌 해소 확인 (최신 코드 기준)", [
  [{ t: "이전 충돌(HEAD_SERVO_PIN 과 FRONT_ENA_PIN 이 GPIO12 공유)은 팀원 커밋 351a1bf 에서 ", }, { t: "HEAD_SERVO_PIN 을 GPIO17(물리 11)로 이동", b: true }, { t: " 하여 해소되었습니다." }],
  [{ t: "현재 Head 18개 핀 모두 중복 없음 → ", }, { t: "check_duplicate_pins() 통과 예상.", b: true }],
  [{ t: "최신 코드 기준 충돌 해소 확인, 실물 구동 검증 필요", b: true, color: "C00000" }, { t: " (실기기에서 헤드 서보·앞모터 동시 동작 확인 전)." }],
], "ok"));

c.push(H2("7-2. Node1 / Node2 / Node3 (동일)"));
c.push(makeTable([3400, 1900, 1900, 2160], [
  ["기능", "BCM GPIO", "물리 핀", "상수명"],
  ["좌 모터 PWM (ENA)", "18", "12", [{ t: "ENA_PIN", code: true }]],
  ["좌 모터 IN1 / IN2", "23 / 24", "16 / 18", [{ t: "IN1_PIN/IN2_PIN", code: true }]],
  ["우 모터 PWM (ENB)", "13", "33", [{ t: "ENB_PIN", code: true }]],
  ["우 모터 IN3 / IN4", "27 / 22", "13 / 15", [{ t: "IN3_PIN/IN4_PIN", code: true }]],
  ["좌 엔코더 A / B", "20 / 21", "38 / 40", [{ t: "LEFT_ENC_A/B", code: true }]],
  ["우 엔코더 A / B", "16 / 26", "36 / 37", [{ t: "RIGHT_ENC_A/B", code: true }]],
  ["분리 서보", "6", "31", [{ t: "DETACH_SERVO_PIN", code: true }]],
]));
c.push(Bullet("Node에는 헤드 서보·앞 DC모터가 없어 핀 충돌이 없습니다 (check_duplicate_pins 통과)."));
c.push(Bullet("Node1/2/3의 핀 정의는 완전히 동일합니다 (Node3는 코드 구조만 다를 뿐 핀은 동일)."));

c.push(H2("7-3. 이전 초안 대비 변경점"));
c.push(Bullet("이전 초안은 분리 서보(GPIO6)만 표기 → 본 문서는 Head의 메인/앞모터/엔코더/헤드서보 전체를 반영."));
c.push(Bullet([{ t: "팀원 커밋 ", }, { t: "351a1bf", code: true }, { t: " 가 ", }, { t: "HEAD_SERVO_PIN 을 12→17", b: true }, { t: " 로 변경하여 GPIO12 충돌을 해소함. 본 문서 핀 표는 이를 반영함." }]));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 8. systemd / 로그 / 복구 ----------
c.push(H1("8. systemd · 로그 · 복구"));
c.push(H2("8-1. systemd 유닛 / install 스크립트"));
c.push(makeTable([2700, 4100, 2560], [
  ["유닛", "실행", "설치"],
  [[{ t: "hansel-ap.service", code: true }], "start_ap.sh --yes (oneshot, ExecStop=stop_ap.sh)", [{ t: "install_head_services.sh", code: true }]],
  [[{ t: "hansel-head-control.service", code: true }], "Head_control.py (UDP 5000)", "동일"],
  [[{ t: "hansel-head-camera.service", code: true }], "run_camera_stream.sh (UDP 5001)", "동일"],
  [[{ t: "hansel-head-monitor.service", code: true }], "run_guard_detach.sh (RSSI+자동분리)", "동일"],
  [[{ t: "hansel-nodeN-control.service", code: true }], "NodeN_control.py (UDP 5000)", [{ t: "install_nodeN_services.sh", code: true }]],
  [[{ t: "hansel-nodeN-relay.service", code: true }], "run_video_relay.sh (UDP 5001)", "동일"],
]));
c.push(P([{ t: "install 스크립트는 enable만 하고 AP/네트워크를 즉시 start 하지 않습니다", b: true }, { t: " — 의도된 안전장치." }]));

c.push(H2("8-2. 로그 확인"));
CodeBlock([
  "journalctl -u hansel-head-control.service -f",
  "journalctl -u hansel-head-monitor.service -f   # 자동분리 이벤트",
  "journalctl -u hansel-nodeN-relay.service -f     # 영상 패킷 통계",
  "tail -f raspberry/head/monitor/logs/monitor.log # --log 사용 시",
]).forEach(x => c.push(x));

c.push(H2("8-3. 장애 복구 빠른 표"));
c.push(makeTable([3400, 5960], [
  ["증상", "조치"],
  ["AP 전환 후 SSH 끊김", [{ t: "콘솔에서 sudo bash ap/stop_ap.sh --yes (Wi-Fi 클라이언트 복귀)", code: true }]],
  ["제어 무반응", [{ t: "systemctl status/​restart hansel-*-control; ping 192.168.4.x", code: true }]],
  ["영상 안 나옴", "Android Wi-Fi/IP(.20) 확인 → 각 relay journalctl 패킷 카운트 → Head camera 서비스 확인"],
  ["분리 안 됨", [{ t: "station_map.conf MAC 반영 여부, detach_state.json latch, hansel-head-monitor 로그 확인", code: true }]],
  ["분리가 다시 안 됨(미션 재시작)", [{ t: "reset_detach_state.sh --yes 후 monitor 재시작", code: true }]],
]));

c.push(new Paragraph({ children: [new PageBreak()] }));

// ---------- 9. 검증 체크리스트 / 상태 ----------
c.push(H1("9. 실물 검증 체크리스트 · 상태표"));
c.push(makeTable([5200, 2080, 2080], [
  ["항목", "코드 확인", "실물 검증"],
  ["GPIO 핀 정의 / 충돌 점검", [{ t: "✔ 충돌 해소(12→17)", color: "375623" }], [{ t: "필요(서보 구동)", color: "C00000" }]],
  ["정적/동적 IP 정책", [{ t: "✔", color: "375623" }], [{ t: "필요", color: "C00000" }]],
  ["UDP 5000 제어 명령 수신", [{ t: "✔", color: "375623" }], [{ t: "필요", color: "C00000" }]],
  ["영상 5001 체인 Head→…→Android", [{ t: "✔", color: "375623" }], [{ t: "필요", color: "C00000" }]],
  ["AP 자동 기동(2nd boot)", [{ t: "✔", color: "375623" }], [{ t: "필요", color: "C00000" }]],
  ["Node AP 자동 재접속", [{ t: "✔", color: "375623" }], [{ t: "필요", color: "C00000" }]],
  ["RSSI→자동분리(detach_press)", [{ t: "✔", color: "375623" }], [{ t: "필요(MAC 반영 후)", color: "C00000" }]],
  ["latch 1회 분리 / reset", [{ t: "✔", color: "375623" }], [{ t: "필요", color: "C00000" }]],
]));
c.push(Spacer());
c.push(Callout("문서 성격 재확인", [
  [{ t: "본 문서는 최신 origin/main(351a1bf) 코드 기준으로 작성된 DRAFT 입니다.", b: true }],
  [{ t: "표의 \"실물 검증 필요\" 항목은 실기기 end-to-end 테스트로 확인되기 전까지 \"동작 확인됨\"으로 간주하지 않습니다." }],
], "warn"));

// build
build("deliverables/HANSEL_GRETEL_DEPLOYMENT_AND_OPERATION_DRAFT.docx",
  "HANSEL/GRETEL 배포·운영 문서 (DRAFT)", c)
  .then(() => console.log("OK public docx"))
  .catch(e => { console.error(e); process.exit(1); });

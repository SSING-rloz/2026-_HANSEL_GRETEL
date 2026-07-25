# 변경 이력

## 2026-07-20 20:56 KST - rosbag 수집·검사 도구 준비

- 생성 파일: `scripts/radar_bag_recorder.py`, `scripts/inspect_radar_bag.py`,
  `docs/RADAR_ODOMETRY_EXPERIMENT_KO.md`
- 수정 파일: `CMakeLists.txt`, 바탕화면 운영 문서
- 목적: 자동 radar odometry 개발 전에 반복 가능한 실험 bag과 메타데이터를 수집·검사
- 테스트 결과: Python 구문/import/help/오류 인자/없는 bag/빈 bag 통과,
  격리된 가짜 PointCloud2·LaserScan 10 Hz 기록 성공, inspector PASS 및 필수 토픽 누락
  FAIL 확인, `catkin_make` 성공
- 정상 동작 여부: 비하드웨어 테스트 정상. 실제 레이더 기록은 아직 시작하지 않음
- 종료 테스트: SIGINT 종료 코드 0, `.active` 잔존 0개, YAML 생성 및 bag 내부 길이 일치
- 기존 기능 영향: driver, parser, LaserScan, RViz, mapping, launch는 수정하지 않음
- 되돌리는 방법: 사전 스냅샷의 `iwrl6432_ros`를 참고해 이번 신규 파일과 CMake 신규 두 줄만 복원
- 다음 작업: `static_15s` 실제 레이더 실험

## 2026-07-20 21:06 KST - 첫 `static_15s` 실데이터 수집

- 생성 파일: `~/iwrl6432_mapping_ws/bags/static_15s_20260720_210606.bag` 및 동명 YAML
- 수정 파일: `scripts/radar_bag_recorder.py`, `scripts/inspect_radar_bag.py`,
  `docs/RADAR_ODOMETRY_EXPERIMENT_KO.md`, 프로젝트 상태·개발 노트
- 수정 목적: 실제 bag에 저장된 토픽만 YAML에 기록하고, 1 Hz 선택 토픽을 데이터 공백으로
  오판하지 않도록 point/scan에만 공백 판정을 적용
- 테스트 결과: 14.836초, 525 messages, points/scan 약 4.70 Hz, SIGINT 정상 종료,
  `.active` 없음, inspector WARNING, catkin 빌드 및 기존 테스트 4개 통과
- 정상 동작 여부: 기록 도구 정상. 데이터는 평균 point width 0.571, 빈 point frame
  78.571%, 유효 scan 0개인 연속 구간 때문에 odometry 용도로 WARNING
- 기존 기능 영향: driver, parser, LaserScan, RViz, mapping, launch 수정 없음
- 되돌리는 방법: 사전 스냅샷에서 recorder/inspector/문서/CMake 상태를 복원한다. 수집한
  bag과 YAML은 독립 데이터이므로 코드 복원과 무관하다.
- 다음 작업: 고정 특징물이 더 잘 보이는 배치에서 `static_15s` 재수집 검토

## 2026-07-20 21:54 KST - 실시간 3D Rolling Local Map

- 생성 파일: `scripts/radar_3d_rolling_map_node.py`,
  `scripts/radar_3d_fov_guides_node.py`, `launch/iwrl6432_live_3d.launch`,
  `config/iwrl6432_live_3d.rviz`, `docs/RADAR_3D_ROLLING_MAP_KO.md`,
  `test/test_radar_3d_rolling_map.py`
- 수정 파일: `CMakeLists.txt`, 시행가이드 및 상태/개발 문서
- 목적: radar_link 기준 최근 4초 x/y/z 포인트의 실시간 local 3D visualization
- 테스트 결과: elevation -20/-10/0/30/60/70 경계, voxel, max_points, 4초 삭제,
  pause/resume, clear, 빈 frame, 필드 보존, latched guide 통과. catkin 테스트 8개 통과
- 실제 결과: raw/filtered 약 4.703 Hz, rolling 10 Hz, rolling width 3~5점,
  RViz 3D wireframe와 cloud Display OK
- 정상 동작 여부: rolling 기능 정상. 실제 raw z는 표본 31점 모두 0.0이라 높이 변화는 미관측
- 기존 기능 영향: driver, parser, LaserScan, manual mapping, MotionDetect.cfg 및 기존 launch 변경 없음
- 되돌리는 방법: `snapshots/before_live_3d_20260720_214254`를 참고해 신규 파일과 CMake
  신규 항목만 제거한다. 기존 정상 파일은 그대로다.
- 다음 작업: z가 비영인 실제 firmware/output 조건 확인 또는 radar odometry 좌표 보상 검토

## 2026-07-20 22:06 KST - 실제 센서 방향 Marker와 FOV 정렬

- 수정 파일: `scripts/radar_3d_fov_guides_node.py`,
  `config/iwrl6432_live_3d.rviz`, `CMakeLists.txt`, 3D 가이드 테스트 및 문서
- 목적: RViz 기본 XYZ 색상만으로 혼동하지 않도록 실제 센서 정면/좌우/위 방향 표시
- 실측 결과: 정면 `+Y`, 왼쪽 `-X`, 오른쪽 `+X`, 위 `+Z`
- 생성 Marker: RADAR FRONT, LEFT, RIGHT, UP 화살표·텍스트 및 SENSOR ORIGIN 구/텍스트
- FOV: 기존 +X 중심에서 실제 +Y 중심 수평 ±60°, elevation -10~+60°로 정렬
- 테스트 결과: Python 구문, 축 단위 테스트, Marker ID 18개, lifetime 0, ADD only,
  FOV 중심 +Y, catkin 전체 테스트 12개 통과
- 기존 기능 영향: driver/parser/LaserScan/manual mapping/MotionDetect.cfg 변경 없음
- 되돌리는 방법: `snapshots/before_direction_guides_20260720_220348`의 가이드/RViz/CMake를 복원
- 다음 작업: 사용자가 Orbit 카메라로 UP과 실제 z 높이 방향을 시각 확인

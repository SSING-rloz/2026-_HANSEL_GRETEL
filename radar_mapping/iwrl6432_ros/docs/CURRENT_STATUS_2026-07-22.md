# Current Status — 2026-07-22

## 공식 상태

현재 기준 기능은 실제 3D 반사점, 5-sector occupancy, 최근 3-frame risk, clear-run, Low-Occupancy Corridor, Recommended Heading 및 간결한 3D RViz이다. 계산·설정 변경 없이 Scene A/B/C가 검증됐다.

## 현재 정상 핵심 파일과 SHA-256

| 파일 | SHA-256 |
|---|---|
| `scripts/radar_driver_node.py` | `f1f177f9348178a9948d33ce8f7ed1b82da298d867c3f8e298a3be1e208abc91` |
| `scripts/radar_background_calibrator.py` | `25cfd3437b5d2ae0c16bbaac557b5f51661655b08b2a5ff93c51c74c8f0d29a5` |
| `scripts/radar_sector_occupancy_node.py` | `cd448b1297e7e9259c12d098b122315085cdf40f3caa09a3cb8d42b7cc70f1b0` |
| `src/iwrl6432_ros/sector_occupancy.py` | `82177ffc546e8bd300274dc861447e3a9ecfcf3db79b7de45cca6a8057b7aad4` |
| `scripts/radar_obstacle_contour_node.py` | `dc722e75e9abcf79b9762bff9a965f2cb1962d07257bf2230b26a564daa63a57` |
| `launch/radar_sector_occupancy_test.launch` | `995a994f7cf5c241b79617282fb79bea43b933561665c9707e3b2b9d8cf6e229` |
| `rviz/radar_sector_occupancy_3d.rviz` | `51784e2fae1b3ff065c0a8be61e1b062a9fb858ff5001c265d4512df86a2e6f4` |
| `test/test_radar_sector_occupancy.py` | `a62029e2e83837cbbcc5674218075a850d394eb27d25a28b8546ea3b810b5cb7` |
| `CMakeLists.txt` | `94464e21f1b7e0bf01b729742476d6dd9a429d203579b6c42e6731e0ab67e705` |
| `package.xml` | `6f3ecae107834d6e90219330dd71bfe7f19e1cd46348c59a14624c00ef0fbaf9` |
| `config/StaticObstacleNearField1m.cfg` | `b827e0b4f651346fa60746e3499f6067a332563dc207cdf067237c8a89fbf1e1` |
| `config/MotionDetect.cfg` | `9ff722bb3ee00d6f5fb051d9990addaf3760954f49040235b479dc71a8dc6edc` |

요청된 `scripts/radar_driver.py`는 존재하지 않으며 실제 driver는 `scripts/radar_driver_node.py`이다. 각 파일의 크기와 수정 시각은 기준선 `validation_results/file_metadata_sha256.txt`에 별도 기록한다. 알려진 MotionDetect.cfg hash와 실제 hash는 일치한다.

## ROS topic

- `/radar/points`
- `/radar/sector_points`
- `/radar/background_points`
- `/radar/sector_occupancy`
- `/radar/sector_nearest_ranges`
- `/radar/sector_recommended_heading`
- `/radar/sector_markers`
- `/radar/low_occupancy_corridor`
- `/radar/low_occupancy_corridor_markers`

## Launch, cfg 및 RViz

- 기준 launch: `launch/radar_sector_occupancy_test.launch`
- driver port: `/dev/ttyACM0`
- 기준 cfg: `config/StaticObstacleNearField1m.cfg`
- cfg 주요값: `rangeSelCfg 0.1 1.0`, `clutterRemoval 0`
- 비교 보존 cfg: `config/MotionDetect.cfg`
- RViz: `rviz/radar_sector_occupancy_3d.rviz`
- Raw Radar Points와 Sector Points 활성화, Background Points 비활성화
- 0.2 m 거리 원호와 라벨, FRONT, 한 줄 sector 상태, 한 줄 PATH, 추천 화살표
- 거리 원호 및 3D guide line width 0.0035 m
- 3D guide z=-0.40~+0.40 m, 원호와 동일 RGB, alpha 0.20
- legacy outline/gap 기본 비활성화

## 검증 결과

- Scene A: 전 sector clear, 중앙 corridor, heading 0°, 상태 변경 없음
- Scene B: S2/S4 occupied, S3 clear 및 corridor, heading 0°, 45/45 frame, 상태 변경 없음
- Scene C: S3 occupied, S4–S5 corridor, heading 약 +24°, 45/45 frame, 상태 변경 없음
- Scene D: 전체 차단을 시도했으나 S1/S4 반사가 부족했다. 실측 44 frame에서 S2/S3/S5만 occupied였고 데이터상 S4 corridor가 선택됐다. 알고리즘 오류가 아니라 모든 sector 반사 조건 미성립으로 분류한다.

## 검사 상태

- Python syntax: 통과
- launch XML 및 package.xml: 통과
- unit test: 66/66 통과
- catkin_make: 통과
- 실제 radar point: 약 4.70 Hz
- TF `base_link -> radar_link`: translation 0, yaw -90°로 정상 발행
- XDS110 `/dev/ttyACM0`, `/dev/ttyACM1`: 정상 열거

세부 출력은 기준선의 `validation_results/`와 `runtime_snapshot/`에 저장한다.

## 현재 /tmp 결과 경로

- `/tmp/iwrl6432_scene_b_check/`
- `/tmp/iwrl6432_scene_c_check/`
- `/tmp/iwrl6432_scene_d_check/`
- `/tmp/iwrl6432_safe_corridor_validation/`
- `/tmp/iwrl6432_safe_corridor_runtime/`

요청된 기존 결과 디렉터리 중 실제 존재하는 항목만 기준선에 복사하고, 없는 경로는 복사 상태 목록에 기록한다.

## 미완료 사항

- 실제 모든 sector에서 충분한 반사가 있는 전체 차단 조건 검증
- 동적 장애물 시험
- 거리·재질·표면각별 검출률
- 센서 또는 로봇 이동 시험
- Clear/Occupied/Unknown 및 confidence 정책
- camera confidence 연계와 상위 주행 인터페이스

## Neighbor voxel background matching

Background profile 경계에서 측정 jitter로 exact voxel index가 한 칸 바뀌는 경우를
흡수하도록 3D Chebyshev 이웃 matching을 추가했다. 기본
`background_neighbor_voxel_radius:=0`이 기본값이며 기존 exact matching 동작을
유지한다. 검증 시 명시적으로 `1`을 설정하면 profile voxel을 중심으로 3x3x3 영역을
검색한다. 이 기능은 사전에
calibration된 background profile 주변에만 적용되고 Reflection Object 분류와는
독립적이다.

전체 차단 시험을 성공할 때까지 장애물 배치만 무작정 반복하지 않는다.

## 다음 작업 우선순위

1. 현재 정상 상태 기준선 보존
2. 움직이는 장애물 시험
3. 거리·재질·표면각 검출률 시험
4. Clear/Occupied/Unknown 정책 설계
5. camera confidence interface 설계

## 2026-07-22 Vertical ROI 및 금속 캔 실환경 검증 최종 상태

### 현재 실행 상태

- Ubuntu 20.04.6 LTS, ROS1 Noetic
- radar driver, sector occupancy node, RViz 각 단일 인스턴스 정상
- `/radar/points` 약 4.70 Hz
- `sector_min_z=-0.05`, `sector_max_z=0.30`
- `background_neighbor_voxel_radius=0`
- background profile은 `/tmp/iwrl6432_sector_occupancy_reconnected_0722_VgjDeUWq/background_profile.yaml`

### Vertical ROI

`sector_min_z <= z <= sector_max_z`인 non-background point만 sector risk와
`/radar/sector_points`에 전달한다. `/radar/points`와 `/radar/background_points`는
변경하지 않는다. parameter가 없거나 `-inf/inf`이면 기존 무제한 동작이다. 빈 공간
검증에서 `-0.05~0.30 m`는 음수 z S3/S5 ghost를 제거하면서 z=0인 금속 캔을
보존했다. `0.02~0.30 m`는 S4 ghost와 함께 실제 캔도 제거하므로 채택하지 않았다.

### Scene 2~5 결과

- Scene 2: 센서 회전에 따라 z=0 persistent 반사가 S4, S1, S3 등으로 이동하거나
  소실됐다. 중심 자세 복귀 결과도 최초 중심과 일치하지 않아 multipath/self-reflection
  민감성이 확인됐다. heading은 대부분 0도였고 우회전에서 6회 변경됐다.
- Scene 3: 정면 캔은 1.0 m에서 안정 검출되지 않았고, 0.7 m에서 0.695 m,
  0.5 m에서 0.496/0.517 m로 S3에서 100% persistence로 검출됐다.
- Scene 4: 좌측 캔은 S1/S2, 우측 캔은 S4/S5에서 구분됐다. 다만 기존 ghost와
  복수 occupied sector 때문에 heading은 좌우 모두 약 0도로 유지돼 장애물 반대 방향
  권고가 명확하지 않았다.
- Scene 5: 정면 캔 제거 후 첫 수신 frame(약 0.27초)에서 캔 point가 없었고 S3 CLEAR,
  중앙 corridor 및 0도 heading이 모두 복구됐다. 캔 제거 이후 20초간 캔 cluster는
  재검출되지 않았다.

### 확인된 특성과 남은 문제

- 실제 캔은 배치 거리와 range가 대응하고 좌우 이동에 따라 sector가 바뀌며 제거 후
  소실됐다.
- z=0 반사는 센서 회전에 따라 좌표와 sector가 크게 변해 multipath/self-reflection
  ghost 성격을 보인다.
- 가장 큰 문제는 단일 persistent ghost도 높은 risk와 OCC를 만들 수 있고, 그 결과
  좌우 캔 배치에서도 recommended heading이 장애물 반대편으로 명확히 변하지 않는다는
  점이다.

### 다음 개발일 첫 작업

저장된 Scene 2/4 데이터를 이용해 **S4 z=0 ghost와 실제 캔을 구분할 수 있는 시간적
association 기준을 오프라인에서 평가**한다. 런타임 risk 식이나 filter는 평가 결과와
안전 기준이 확정되기 전까지 변경하지 않는다.

통합 보존 경로:
`/home/stier/바탕화면/radar/0722_final/scene_validation_20260722_203815`

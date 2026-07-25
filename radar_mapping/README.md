# TI IWRL6432BOOST ROS1 Radar Mapping

재난 탐사 로봇을 위한 TI IWRL6432BOOST mmWave 레이더 ROS1 시스템입니다. 연기,
먼지, 어두운 공간 등 저가시성 환경에서 사람과 장애물을 감지하는 기반을 만들기
위해 개발했습니다. 현재는 사람이 센서를 이동시키며 pose를 직접 입력하는 handheld
mapping을 먼저 검증했으며, 이후 다관절 재난 탐사 로봇에 이식할 예정입니다.

## 개발자

- GitHub: [jaehyeok012](https://github.com/jaehyeok012)
- 담당: IWRL6432BOOST UART, TLV parser, ROS1 PointCloud2/LaserScan, RViz
  visualization, manual-pose mapping

## 지원 환경

- Ubuntu 20.04
- ROS1 Noetic
- TI IWRL6432BOOST
- MMWAVE-L-SDK 05.05.04.02 Motion and Presence Detection Demo
- Python 3

## 완료 기능

- XDS110 `/dev/ttyACM0` UART 연결 및 `MotionDetect.cfg` 자동 전송
- 115200 → 1,250,000 baud 전환
- `sensorStart`/`sensorStop 0`과 안전한 포트 종료
- TI TLV packet parsing 및 x/y/z, Doppler, SNR, noise 추출
- `sensor_msgs/PointCloud2`, `sensor_msgs/LaserScan` 발행
- RViz 실시간 표시
- 0.5 m 간격, 최대 3 m 전방 반원 가이드
- 0~1 m collision risk, 1~2 m slow/avoid, 2~3 m path planning 표시
- 수동 Pose2D 기반 누적 handheld mapping

## 전체 파이프라인

```mermaid
flowchart LR
    A[IWRL6432BOOST] --> B[XDS110 UART]
    B --> C[radar_driver_node]
    C --> D[TI TLV parser]
    D --> E[/radar/points]
    E --> F[radar_to_laserscan]
    F --> G[/radar/scan]
    E --> H[manual_pose_mapping]
    I[/radar/manual_pose] --> H
    H --> J[/radar/map_points]
    E --> K[RViz]
    G --> K
    J --> K
    L[radar_rviz_guides] --> K
```

## ROS 노드

| 노드 | 역할 |
|---|---|
| `radar_driver` | UART 설정, TLV parsing, PointCloud2 발행 |
| `radar_to_laserscan` | PointCloud2를 2D LaserScan으로 변환 |
| `radar_rviz_guides` | 거리 반원, 방향, 위험 구간 MarkerArray 발행 |
| `manual_pose_mapping` | 수동 pose로 포인트를 map 좌표에 누적 |
| `base_to_radar` | `base_link → radar_link` static TF |
| `rviz` | 실시간 데이터와 누적 map 시각화 |

## ROS 토픽

| 토픽 | 타입 | 발행 노드 | 용도 |
|---|---|---|---|
| `/radar/points` | `sensor_msgs/PointCloud2` | `radar_driver` | 현재 radar point cloud |
| `/radar/scan` | `sensor_msgs/LaserScan` | `radar_to_laserscan` | 2D 거리 scan |
| `/radar/rviz_guides` | `visualization_msgs/MarkerArray` | `radar_rviz_guides` | RViz 방향·거리·안전 구간 |
| `/radar/map_points` | `sensor_msgs/PointCloud2` | `manual_pose_mapping` | map 좌표 누적 cloud |
| `/radar/manual_pose` | `geometry_msgs/Pose2D` | 사용자 도구 | 현재 수동 pose 입력 |
| `/radar/current_pose` | `geometry_msgs/Pose2D` | `manual_pose_mapping` | 적용 중인 pose 확인 |
| `/tf` | `tf2_msgs/TFMessage` | TF 노드들 | 동적/주기 TF |
| `/tf_static` | `tf2_msgs/TFMessage` | 환경에 따라 사용 | 정적 TF 채널 |

## 좌표계

ROS REP-103 기준으로 +X는 전방, +Y는 왼쪽, +Z는 위입니다. 현재 후보 축 매핑은
`ROS x=radar y`, `ROS y=-radar x`, `ROS z=radar z`이며 launch에서
`base_link → radar_link` yaw `-90°`를 적용합니다. 이 값은 현재 센서 방향 후보에
맞춘 것이므로 실제 로봇 장착 방향을 측정한 뒤 extrinsic을 수정해야 합니다.

수동 mapping에서는 사용자가 입력한 pose로 `map → base_link`를 발행하고 기존
`base_link → radar_link`와 연결합니다.

## 설치

```bash
mkdir -p ~/catkin_ws/src
cp -a radar_mapping/iwrl6432_ros ~/catkin_ws/src/
source /opt/ros/noetic/setup.bash
cd ~/catkin_ws
catkin_make
source ~/catkin_ws/devel/setup.bash
rospack find iwrl6432_ros
```

사용자는 serial 접근을 위해 `dialout` 그룹에 속해야 합니다. 그룹 추가 후에는 다시
로그인합니다. 레이더 연결 후 `/dev/ttyACM0`이 있는지 확인합니다.

```bash
groups
ls -l /dev/ttyACM0
```

## 실행

이전 launch가 완전히 종료됐는지 확인하고 보드의 RESET_SW를 한 번 누릅니다.
RESET은 CLI를 초기 115200 baud 상태로 되돌려 driver와 baud 상태를 맞추기 위해
필요합니다.

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
roslaunch iwrl6432_ros iwrl6432.launch
```

## RViz 화면 해석

- **Radar Points**: 현재 프레임 PointCloud2
- **Radar Scan**: 각도 bin별 최근접 2D 거리
- **Accumulated Radar Map**: 수동 pose로 누적된 map cloud
- **Radar Guides**: 0.5~3.0 m 전방 반원과 위험 구간
- **FRONT +X / LEFT +Y / RIGHT -Y**: 방향 기준
- **SENSOR ORIGIN**: 센서 기준 원점

위험 구간 배경은 0~1 m 충돌 위험, 1~2 m 감속·회피, 2~3 m 경로 계획을 뜻합니다.

## 수동 pose mapping

`publish_manual_pose.py`의 yaw 기본 단위는 degree입니다.

```bash
rosservice call /radar/clear_map
rosrun iwrl6432_ros publish_manual_pose.py 0.0 0.0 0.0
# 2~3초 정지 후 실제로 0.5 m 이동
rosrun iwrl6432_ros publish_manual_pose.py 0.5 0.0 0.0
# 다시 이동 후
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 0.0
# 현재 위치에서 왼쪽 90° 회전
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 90.0
```

Radian 입력은 `--radians`를 사용합니다. pose를 한 번도 입력하지 않으면 map에
누적하지 않습니다.

## 정상 동작 기준

- `/radar/points`, `/radar/scan` 약 4.7 Hz
- frame당 point 수는 사람·장애물·SNR 등 환경에 따라 변동
- RViz에서 PointCloud2와 LaserScan 표시
- 설정 단계에서 `sensorStart` 승인
- Ctrl+C 종료 시 `sensorStop 0 sent`
- 종료 후 `/dev/ttyACM0` 점유 해제

## 알려진 한계

- 자동 SLAM이 아니며 manual pose 입력 필요
- 자동 radar odometry, IMU, encoder 없음
- sparse point cloud라 벽이 LiDAR처럼 연속선으로 보이지 않을 수 있음
- dynamic/static object 분리 미구현
- 이동 플랫폼에서 Doppler를 사용하려면 ego-motion 보상 필요
- 수동 pose 갱신 사이 이동 중 포인트를 일시정지하는 기능은 아직 없음

## 향후 개발

rosbag 수집 → static/straight/rotation/L-shape 실험 → offline scan matching → radar
odometry → IMU fusion → automatic handheld mapping → robot integration → encoder +
IMU + radar odometry → slip detection 순으로 진행할 계획입니다.

## 주의사항

- 같은 roslaunch를 두 번 실행하지 마십시오. 노드 이름 충돌과 UART busy가 납니다.
- busy 발생 시 기존 프로젝트 launch를 정상 종료하고 `fuser -v /dev/ttyACM0`으로
  점유 해제를 확인한 뒤 RESET하고 한 번만 실행하십시오.
- launch 종료 후 RViz만 남으면 토픽이 끊겨 display가 빨간색이 됩니다.
- 공개 저장소에는 TI 저작권 자료와 불필요한 대용량 파일을 피하기 위해 TI SDK
  전체, firmware appimage, 원본 HTML/PDF 문서를 포함하지 않았습니다.

자세한 절차는 [`docs/시행가이드.txt`](docs/시행가이드.txt), 구조는
[`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md), 문제 해결은
[`docs/TROUBLESHOOTING_KO.md`](docs/TROUBLESHOOTING_KO.md)를 참고하십시오.

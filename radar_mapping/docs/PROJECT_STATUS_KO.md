# IWRL6432 ROS1 프로젝트 상태

## A. 프로젝트 목적

TI IWRL6432BOOST 레이더를 Ubuntu 20.04의 ROS1 Noetic에 연결하여 PointCloud2와
LaserScan을 발행하고 RViz에서 시각화한다. 현재는 사람이 레이더를 손으로 이동하며
Pose2D를 입력하는 handheld mapping 단계이며, 이후 자동 radar odometry와 로봇
이식을 진행할 예정이다.

## B. 현재 정상 동작 항목

- `/radar/points`와 `/radar/scan` 약 4.7 Hz 실시간 발행
- RViz PointCloud2, LaserScan 표시
- 0.5 m 간격, 최대 3 m의 전방 반원 Radar Guides 표시
- 충돌 위험, 감속·회피, 경로 계획 구간 표시
- 수동 pose 기반 `/radar/map_points` 누적 mapping 성공
- 종료 시 `sensorStop 0` 전송 및 UART 점유 해제

## C. 현재 ROS 토픽

`/radar/points`, `/radar/scan`, `/radar/rviz_guides`, `/radar/map_points`,
`/radar/manual_pose`, `/radar/current_pose`, `/tf`, `/tf_static`.

## D. 현재 ROS 노드

`radar_driver`, `radar_to_laserscan`, `radar_rviz_guides`,
`manual_pose_mapping`, `base_to_radar`, `rviz`.

## E. 현재 좌표계

- 프레임 체인: `map -> base_link -> radar_link`
- ROS 기준: +X 전방, +Y 좌측, +Z 위
- 현재 검증 후보: `ROS x=radar y`, `ROS y=-radar x`, `ROS z=radar z`
- `base_link -> radar_link`: translation `(0,0,0)`, yaw `-90°`
- `map -> base_link`: 사용자가 입력한 수동 Pose2D로 발행

## F. 현재 설정

- CLI 포트: `/dev/ttyACM0`, 8N1, flow control 없음
- 초기 baud: 115200, `baudRate` 명령 후 1,250,000
- 설정 파일: `config/MotionDetect.cfg`
- radar driver 기본 필터: range 0~20 m, SNR 0, z -10~10 m
- LaserScan: 0.25~7.5 m, 약 ±80°, 1° bin, SNR 15, z -0.5~0.5 m,
  temporal window 3
- RViz guide: 0~3 m 전방 반원, 0.5 m 간격, 시각화 FOV ±90°
- manual mapping: SNR 15, range 0.2~3.0 m, z -0.5~0.5 m,
  voxel 0.05 m, 최대 100,000점

## G. 알려진 주의사항

- 같은 launch를 중복 실행하면 노드 이름 충돌과 UART busy가 발생한다.
- launch 종료 후 RViz만 남으면 토픽 display가 빨간색이 되는 것이 정상이다.
- 실행 전 RESET_SW를 눌러 초기 115200 baud 상태를 확보한다.
- UART quiet wait에는 최대 대기시간과 종료 보호가 적용돼 있다.
- wheel odometry, IMU, 자동 scan matching은 아직 없다.
- 현재 mapping은 사람이 레이더를 이동시키고 pose를 직접 입력한다.
- 로봇 이식은 이후 단계다.

## H. 다음 개발 단계

1. rosbag 데이터 수집
2. static 15초, 직선 1 m, 90° 회전, L자 경로 실험
3. 오프라인 scan matching
4. radar odometry
5. IMU 융합
6. 로봇 encoder와 결합

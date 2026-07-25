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

1. rosbag recorder/inspector 코드 준비 및 비하드웨어 테스트
2. `static_15s` 실제 데이터 수집
3. 직선 1 m, 90° 회전, L자 경로 실험
4. 오프라인 scan matching
5. radar odometry
6. IMU 융합
7. 로봇 encoder와 결합

## I. rosbag 도구 상태

- recorder: 필수 토픽 사전 검사, Hz 측정, 정상 신호 종료, YAML 생성 지원
- inspector: point/scan/TF/공백 통계와 odometry 사용 가능 PASS/WARNING/FAIL 판정 지원
- 기본 bag 위치: `~/iwrl6432_mapping_ws/bags`
- Python 정적 검사, 오류 처리, 가짜 10 Hz bag, SIGINT, YAML, inspector, catkin 빌드 통과
- 실제 레이더 `static_15s` 기록은 사용자 준비 후 별도로 수행

## J. 첫 실제 `static_15s` 결과

- 2026-07-20 21:06 KST 수집 완료, SIGINT 정상 종료 및 YAML 생성
- bag 길이 14.836초, points/scan 약 4.70 Hz, 필수 radar 토픽 장시간 공백 없음
- inspector `WARNING`: point가 매우 희소하고 빈 scan이 연속되는 구간 존재
- recorder와 inspector 동작은 정상이나 odometry 학습/개발용 데이터 품질은 개선 권장
- 다음 단계 전 고정 특징물이 풍부한 환경에서 static 실험 재수집 여부를 결정

## K. 실시간 3D Rolling Local Map

- 별도 `iwrl6432_live_3d.launch` 실행 성공
- `/radar/points_3d_filtered` 약 4.703 Hz, `/radar/rolling_map_3d` 10 Hz
- radar_link 기준 최근 4초 frame, voxel 0.05 m, 최대 50,000점 관리
- 수평 총 120도, elevation -10도~+60도, 1/2/3 m 3D wireframe 표시
- clear 및 pause/resume 서비스 제공
- 전역 SLAM이 아니며 레이더 이동 시 cloud도 local frame을 따라 이동
- 실제 MotionDetect raw 표본 31점의 z는 모두 0.0. 3D elevation 기능은 가짜 입력으로 검증
- 기존 driver/parser/LaserScan/manual mapping/MotionDetect.cfg는 변경하지 않음

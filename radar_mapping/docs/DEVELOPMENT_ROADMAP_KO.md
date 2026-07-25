# 개발 로드맵

## 완료

- IWRL6432BOOST XDS110 UART와 CLI 설정 자동화
- TI TLV parser와 raw packet 검증
- ROS1 PointCloud2 및 LaserScan
- RViz 전방 반원 guide와 위험 구간
- 수동 Pose2D 기반 handheld mapping
- 종료 시 sensorStop과 UART 해제

## 현재: handheld mapping 품질 검증

- 고정 환경에서 반복 측정
- 0 m, 0.5 m, 1.0 m 직선 이동
- 제자리 90° 회전
- L자 경로
- 높이와 방향을 일정하게 유지한 재현성 평가

## 데이터 수집

동일한 실험 시나리오를 rosbag으로 기록하고 ground truth 이동량, 환경 배치,
센서 높이, 시간 구간을 함께 기록한다. static 15초 데이터부터 시작한다.

## Offline scan matching과 radar odometry

sparse/noisy point 특성에 맞는 대응점, outlier 제거, 정적점 선택을 평가한다. ICP,
NDT 등을 바로 실시간 적용하기 전에 bag을 사용해 offline 결과와 실패 조건을
비교한다. 이후 frame-to-frame 또는 submap 기반 radar odometry를 구현한다.

## IMU fusion과 자동 handheld mapping

IMU angular velocity와 orientation으로 회전 추정을 보강하고 radar odometry와
융합한다. 수동 Pose2D 없이 `map → base_link`를 추정하는 자동 handheld mapping으로
확장한다.

## 로봇 이식과 slip detection

실제 extrinsic calibration 후 다관절 재난 탐사 로봇에 장착한다. encoder 단독 사용은
공회전과 걸림을 구분하지 못하므로 encoder, IMU, radar odometry를 융합한다. encoder
이동량과 radar 환경 이동량의 차이를 slip/걸림 지표로 사용한다.

## 재난 현장 시험

저가시성, 좁은 통로, 먼지, 동적 사람, 반사 재질, 충격과 진동 조건에서 detection,
odometry drift, map 일관성, recovery 동작을 단계적으로 평가한다.

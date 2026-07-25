# 개발 노트

## rosbag recorder / inspector 설계

- 실행용 패키지: `~/catkin_ws/src/iwrl6432_ros`
- bag 기본 경로: `~/iwrl6432_mapping_ws/bags`
- recorder는 ROS master, 필수 토픽 존재, 실제 메시지 수신, 발행 Hz를 순서대로 검증한다.
- 필수 토픽은 `/radar/points`, `/radar/scan`, `/tf`, `/tf_static`이다.
- 선택 토픽은 현재 발행 중일 때만 기록한다.
- 종료 시 SIGINT를 우선하고 10초 뒤 SIGTERM으로 단계적으로 종료한다.
- 실측하지 않은 환경·거리·회전·높이·이동 시간은 YAML에서 `null`을 유지한다.
- inspector 임계값은 패키지 실험 문서와 소스 상단 주석에 기록했다.
- 실제 레이더 기록은 코드와 가짜 데이터 테스트 이후 사용자 준비 완료를 기다린다.

## 2026-07-20 비하드웨어 검증 결과

- 가짜 `/radar/points`, `/radar/scan`, `/tf`, `/tf_static`: 약 10 Hz
- 완료 bag 내부 길이: 3.900초, `.active` 잔존 없음
- 미제공 YAML 실측 필드: 모두 `null`
- 정상 가짜 bag: inspector PASS
- `/radar/scan` 제거 bag: inspector FAIL
- ROS master 없음, 없는 bag, 빈 bag, 잘못된 실험 이름: 명확한 오류와 기록 거부
- `catkin_make`: 성공, 신규 두 스크립트의 devel wrapper 생성 확인

## 첫 실제 `static_15s` 결과

- bag: `static_15s_20260720_210606.bag`
- 길이/크기: 14.836초 / 4,559,723 bytes
- point/scan: 각각 70 messages, 약 4.700 Hz
- 평균 point width 0.571, 최소 0, 최대 6, 빈 frame 78.571%
- scan finite range 평균 1.443, 최소 0, 최대 13
- 필수 radar 토픽 자체의 1초 초과 공백은 없음
- inspector: WARNING (연속 빈 scan, 희소 point)
- `/tf_static`은 topic 이름만 남아 있고 publisher가 없었다. 기존 고정 변환은 `/tf`에서
  약 20 Hz로 정상 기록되므로 launch는 변경하지 않았다.
- inspector 공백 경고는 odometry 입력인 points/scan만 대상으로 보정했다.

## 실시간 3D Rolling Map 구현 노트

- PointCloud2의 x/y/z/doppler/snr/noise를 가능한 범위에서 유지한다.
- elevation은 원본 radar 좌표에서 `atan2(z, hypot(x,y))`로 계산한다.
- FLOAT32 경계 오차를 위해 1e-5도의 수치 허용오차만 사용한다.
- frame별 timestamp를 deque에 저장하고 `history_sec` 이상 오래되면 삭제한다.
- voxel마다 최신 포인트를 유지하고 max_points 초과 시 오래된 순서부터 제외한다.
- pause 중에는 신규 frame과 history 삭제를 모두 멈춰 화면을 유지한다.
- output_frame이 입력과 다르면 TF를 조회해 xyz를 실제 변환하며 frame 이름만 바꾸지 않는다.
- 3D guide는 latch, lifetime 0, ADD marker만 사용하며 DELETEALL을 반복하지 않는다.
- 실제 검증: raw/filtered 4.703 Hz, rolling 10 Hz, frame radar_link, guide marker 8개.
- 실제 raw z: 31개 표본 모두 0.0. 필터/rolling 문제가 아니라 현재 입력 데이터 특성이다.

## 실제 radar 축 검증

- `/radar/points.header.frame_id`: `radar_link`
- 정면 앞뒤 이동: 199점, y 0~2.301 m, mean |y| 0.799 m vs mean |x| 0.213 m
- 왼쪽 이동: 85점 중 x<0 78개, 평균 x -0.852 m
- 오른쪽 이동: 60점 중 x>0 56개, 평균 x +0.545 m
- 확정 축: FRONT +Y, LEFT -X, RIGHT +X, UP +Z
- TF: base->radar translation 0, quaternion (0,0,-0.707,0.707), yaw -90°
- 기존 2D 변환 `base_x=radar_y`, `base_y=-radar_x`, `base_z=radar_z`와 일치
- FOV spherical 좌표는 x=-r*cos(elev)*sin(az), y=r*cos(elev)*cos(az),
  z=r*sin(elev)로 변경. 양의 azimuth는 물리 LEFT(-X) 방향이다.
- 방향 Marker ID는 100~109로 고정하고 기존 FOV ID 0~7과 분리했다.

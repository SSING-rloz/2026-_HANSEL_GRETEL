# System Architecture

## 구성과 데이터 흐름

IWRL6432BOOST의 XDS110 UART `/dev/ttyACM0` 하나에서 CLI 응답과 binary TLV stream을
처리한다. `radar_driver`가 설정과 parsing을 담당하고 `/radar/points`를 발행한다.
이 cloud는 LaserScan 변환과 수동 mapping으로 나뉘며 RViz가 원본, scan, 누적 map,
guide를 함께 표시한다.

| 구성요소 | 입력 | 출력/역할 |
|---|---|---|
| `radar_driver` | UART, `MotionDetect.cfg` | `/radar/points` |
| `radar_parser.py` | aligned TLV packet | point fields 추출 |
| `radar_to_laserscan` | `/radar/points` | `/radar/scan` |
| `radar_rviz_guides` | 파라미터 | `/radar/rviz_guides` |
| `manual_pose_mapping` | points, Pose2D, TF | `/radar/map_points`, current pose, map TF |

## UART 상태 전환

1. `/dev/ttyACM0`을 115200 baud, 8N1, no flow control로 연다.
2. 최대 시간이 있는 quiet wait 후 기존 입력을 정리한다.
3. CFG 명령별 `Done` 또는 오류 문자열을 확인한다.
4. `baudRate 1250000` 직후 host UART도 1,250,000으로 전환한다.
5. `sensorStart`의 승인을 받은 뒤 binary stream을 parsing한다.
6. 종료 시 `sensorStop 0`을 보내고 file descriptor를 닫는다.

## TLV parsing

Parser는 TI magic word로 packet 경계를 찾고 header의 total packet length와 alignment를
검증한다. 손상되거나 truncated된 packet은 버리고 다음 magic word로 재동기화한다.
알려진 point TLV를 공식 구조에 맞춰 해석하고 unknown TLV는 packet 경계를 유지한 채
건너뛴다.

PointCloud2 필드(모두 `float32`):

| 필드 | 의미 |
|---|---|
| `x`, `y`, `z` | 센서 Cartesian 위치, m |
| `doppler` | radial Doppler |
| `snr` | signal-to-noise ratio |
| `noise` | noise estimate |

## LaserScan 생성

현재 후보 축 매핑으로 radar point를 ROS 평면에 놓고 높이, SNR, 거리 범위를
필터링한다. `angle_min`부터 `angle_max`까지 1° 간격 bin을 만들고 각 bin에 가장
가까운 평면 거리만 남긴다. 검출이 없는 bin은 `+inf`다. 기본적으로 최근 3개
PointCloud2 frame을 누적한다.

## TF 구조

```text
map --(manual Pose2D)--> base_link --(yaw -90°)--> radar_link
```

`map → base_link`는 수동 pose가 입력된 후 `manual_pose_mapping`이 발행한다.
`base_link → radar_link`는 launch의 `base_to_radar`가 발행한다. 실제 장착 방향을
검증한 뒤 yaw와 translation을 수정해야 한다.

## Manual mapping 변환

입력이 `radar_link`이면 TF로 먼저 `base_link`에 한 번 변환한다. 이미
`base_link`인 입력에는 이 변환을 다시 적용하지 않는다. 이후 사용자 pose
`(x_pose, y_pose, yaw)`를 적용한다.

```text
x_map = cos(yaw) * x_base - sin(yaw) * y_base + x_pose
y_map = sin(yaw) * x_base + cos(yaw) * y_base + y_pose
z_map = z_base
```

기본 필터는 SNR 15, range 0.2~3.0 m, z -0.5~0.5 m다. 기본 voxel은 0.05 m,
최대 100,000점이며 오래된 voxel부터 제거한다. `voxel_size=0`이면 원본 point를
시간순 deque에 누적한다.

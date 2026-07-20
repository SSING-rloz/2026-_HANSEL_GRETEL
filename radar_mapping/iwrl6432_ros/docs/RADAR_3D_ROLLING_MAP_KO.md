# IWRL6432 실시간 3D Rolling Local Map

## 개념

`/radar/rolling_map_3d`는 전역 SLAM 지도가 아니다. 자동 pose 추정 없이
`radar_link` 기준 최근 몇 초의 포인트만 유지하는 local visualization이다. 레이더가
움직이면 누적 cloud도 레이더 좌표를 따라 움직이며 전역 위치에 고정되지 않는다.
전역 지도화를 위해서는 향후 IMU 또는 radar odometry와 좌표 변환이 필요하다.

## 실행

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
roslaunch iwrl6432_ros iwrl6432_live_3d.launch
```

이 launch는 driver, 기존 LaserScan, 3D rolling 노드, 3D FOV guide, 전용 RViz를 직접
한 번씩 실행한다. 기존 `iwrl6432.launch`와 동시에 실행하면 안 된다.

주요 출력:

- `/radar/points_3d_filtered`: 현재 frame의 range/SNR/elevation 필터 결과
- `/radar/rolling_map_3d`: 최근 `history_sec`의 voxel 누적 결과
- `/radar/rviz_guides_3d`: 수평 ±60°, elevation -10°~+60°, 최대 3 m wireframe

기본값은 range 0.2~3.0 m, SNR 15 이상, elevation -10°~+60°(경계 포함), history
4초, voxel 0.05 m, 최대 50,000점이다. 희소 데이터에서는 launch argument
`history_sec:=6.0`으로 조정할 수 있지만 오래된 장면이 더 오래 남는 trade-off가 있다.

## 서비스

```bash
rosservice call /radar/clear_rolling_map_3d
rosservice call /radar/pause_rolling_map_3d "data: true"
rosservice call /radar/pause_rolling_map_3d "data: false"
```

pause 중에는 새 포인트를 받지 않고 기존 rolling cloud를 유지한다. resume하면 현재
시간을 기준으로 오래된 frame을 정리한 뒤 누적을 재개한다.

## RViz에서 높이 확인

전용 RViz의 Orbit 카메라를 마우스로 회전해 XY 평면과 Z 높이를 함께 본다. 두
PointCloud2 Display는 `AxisColor`, Axis `Z`, Decay Time `0`이다. history 관리는
RViz가 아니라 노드가 담당한다.

2026-07-20 실제 MotionDetect 데이터 점검에서는 raw 포인트의 z가 모두 0.0이었다.
따라서 현재 화면의 실제 포인트는 평면에 보이지만 노드는 비영 z와 elevation을 보존하도록
가짜 3D PointCloud2로 검증됐다. 이는 전역 3D SLAM 결과가 아니다.

## 실제 센서 방향과 ROS 축

RViz 기본 Axes 색은 X=빨강, Y=초록, Z=파랑이다. `/radar/points`는
`radar_link` 원본 좌표이며 2026-07-20 실제 이동 측정으로 다음을 확인했다.

- `RADAR FRONT`: `+Y` (초록 축), 정면 앞뒤 이동 199점에서 y 0~2.301 m
- `LEFT`: `-X`, 왼쪽 이동 85점 중 78점이 x<0
- `RIGHT`: `+X`, 오른쪽 이동 60점 중 56점이 x>0
- `UP`: `+Z`

`base_link -> radar_link`는 translation `(0,0,0)`, quaternion
`(x=0,y=0,z=-0.7071,w=0.7071)`, yaw -90°다. 따라서 radar `+Y` 정면은
base `+X` 정면으로 회전된다. 센서 장착 방향에 따라 ROS 기본 X축과 물리 센서 정면이
다를 수 있으므로 방향 Marker를 우선 참고한다.

# iwrl6432_ros

TI IWRL6432BOOST의 Motion and Presence Detection Demo UART 출력을 ROS1 Noetic의
`sensor_msgs/PointCloud2`로 변환하는 최소 드라이버입니다.

## 전제 조건

- 보드 펌웨어: MMWAVE-L-SDK 05.05.04.02 Motion and Presence Detection Demo
- CLI 포트: `/dev/ttyACM0`
- 사용자가 `dialout` 그룹에 포함되어 있어야 합니다.
- 초기 UART 속도는 115200이며 `baudRate 1250000` 직후 1,250,000으로 전환됩니다.

패킷 해석은 오프라인 검증을 통과한 `radar_parser.py`를 그대로 사용합니다. 출력
필드는 `x`, `y`, `z`, `doppler`, `snr`, `noise`이며 모두 `float32`입니다.

## 빌드

```bash
source /opt/ros/noetic/setup.bash
cd ~/catkin_ws
catkin_make
source ~/catkin_ws/devel/setup.bash
```

## 실행

보드를 RESET하여 초기 115200 baud 상태로 만든 다음 실행합니다.

```bash
roslaunch iwrl6432_ros iwrl6432.launch
```

발행 토픽은 `/radar/points`, 기준 프레임은 `radar_link`입니다. launch 파일은
`base_link -> radar_link` identity static TF와 RViz를 함께 실행합니다. RViz는 `snr`
필드를 Intensity 색상으로 사용합니다.

주요 launch 인자는 `port`, `config_file`, `frame_id`, `min_snr`, `min_range`,
`max_range`, `z_min`, `z_max`, `rviz`입니다. 초기값은 포인트를 거의 제거하지
않도록 설정되어 있습니다.

종료 시 노드는 `sensorStop 0` 전송을 시도하고 UART를 닫습니다. 이 패키지는
mapping 및 odometry/IMU 결합을 포함하지 않습니다.

## 좌표계와 LaserScan

TI의 Motion and Presence 문서는 출력값을 센서 좌표계의 Cartesian `x`, `y`, `z`
(m)라고 정의하고, world 좌표 변환은 host에서 수행한다고 설명합니다
(`MOTION_AND_PRESENCE_DETECTION_DEMO.html`의 Point Cloud TLV 및 tracker 좌표 설명).
하지만 로컬 문서의 텍스트만으로 센서 각 축의 물리적 방향은 확정되지 않습니다.

ROS REP-103의 `base_link`는 +X 전방, +Y 왼쪽, +Z 위쪽입니다. 현재 launch의
초기 **검증 후보**는 다음과 같으며 실제 좌우/전후 움직임으로 확인해야 합니다.

```text
ROS x =  radar y
ROS y = -radar x
ROS z =  radar z
```

이 후보는 `ros_x_from`, `ros_y_from`, `ros_z_from`과 각 `ros_*_sign` launch
인자로 바꿀 수 있습니다. 이에 맞춘 초기 static TF yaw는 -π/2이며 `radar_yaw`로
변경할 수 있습니다. 확정 전에는 이 값을 로봇의 최종 extrinsic으로 사용하지
마십시오.

`radar_to_laserscan_node.py`는 `/radar/points`를 받아 `/radar/scan`을 발행합니다.
기본 범위는 ±1.396 rad, 각도 간격은 1도, 거리 0.25~7.5 m, 높이 -0.5~0.5 m,
최소 SNR 15 dB이며 최근 3프레임을 누적합니다. 각 bin에는 가장 가까운 평면
거리만 남기고 검출이 없는 bin은 `+inf`입니다.

## RViz 전방 가이드

`/radar/rviz_guides`는 `base_link`의 +X 전방을 기준으로 0~3 m 반원 거리선과
시각화용 위험 구간을 표시합니다. `guide_fov_deg`의 기본값 90도는 가이드의
좌우 경계만 정하는 RViz 시각화 파라미터이며, 실제 센서 FOV나 LaserScan 필터
범위를 변경하지 않습니다.

## 수동 pose 기반 handheld mapping

`manual_pose_mapping_node.py`는 사용자가 입력한 `map -> base_link` pose를 기준으로
`/radar/points`를 `/radar/map_points`에 누적합니다. 입력이 `radar_link`이면 기존
`base_link -> radar_link` TF를 먼저 한 번 적용하므로 레이더 장착 회전이 중복
적용되지 않습니다. ICP, scan matching 또는 자동 odometry는 수행하지 않습니다.

launch의 `enable_manual_mapping` 기본값은 `true`입니다. 최대 포인트 수는
`mapping_max_points:=100000`, voxel 크기는 `mapping_voxel_size:=0.05`이며 voxel을
사용하지 않는 원본 누적 실험은 `mapping_voxel_size:=0.0`으로 실행합니다.

수동 pose의 yaw는 아래 도구에서 기본적으로 **degree**입니다. radian 입력에는
`--radians`를 붙입니다.

```bash
rosrun iwrl6432_ros publish_manual_pose.py 0.0 0.0 0.0
rosrun iwrl6432_ros publish_manual_pose.py 0.5 0.0 0.0
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 0.0
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.5 90.0
# radian 예: rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.5 1.5708 --radians
```

실험은 다음 순서로 진행합니다.

1. 레이더를 시작 위치에 두고 `(x, y, yaw)=(0, 0, 0 deg)`를 발행합니다.
2. 2~3초 정지하여 포인트를 누적합니다.
3. 레이더를 실제로 0.5 m 전진시키고 `(0.5, 0, 0 deg)`를 발행합니다.
4. 다시 2~3초 정지한 뒤 `(1.0, 0, 0 deg)` 위치에서도 반복합니다.
5. 회전 검증은 `(1.0, 0.0, 90 deg)`처럼 실제 pose를 입력합니다.
6. RViz의 `Accumulated Radar Map`이 `map` frame에 누적되는지 확인합니다.

현재 pose는 `/radar/current_pose`에서 확인하며 누적 map 초기화는 다음 서비스로
수행합니다.

```bash
rostopic echo /radar/current_pose
rosservice call /radar/clear_map
```

pose를 한 번도 입력하지 않으면 노드는 경고만 출력하고 포인트를 누적하지
않습니다. 수동 pose 사용 중에는 노드가 `map -> base_link` TF를 발행하며 기존
`base_link -> radar_link` TF는 그대로 유지됩니다.

# IWRL6432 ROS1 빠른 실행

1. 레이더 USB를 연결하고 `/dev/ttyACM0`을 확인한다.
2. 기존 launch가 없는지 확인하고 RESET_SW를 한 번 누른다.
3. 다음을 순서대로 실행한다.

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
roslaunch iwrl6432_ros iwrl6432.launch
```

RViz에서 Base Axes, Radar Guides, Radar Points, Radar Scan, Accumulated Radar Map을
확인한다. Fixed Frame은 `map`이다. pose 입력 전에는 map 누적이 시작되지 않는다.

```bash
# yaw 기본 단위는 degree
rosrun iwrl6432_ros publish_manual_pose.py 0.0 0.0 0.0
rosrun iwrl6432_ros publish_manual_pose.py 0.5 0.0 0.0
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 0.0
# radian 입력은 --radians 사용
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 1.5708 --radians

# 누적 map 초기화
rosservice call /radar/clear_map
```

[주의] 같은 launch를 두 번 실행하지 않는다. 종료는 launch 터미널에서 Ctrl+C로
수행하고 `sensorStop 0 sent`를 확인한다. RViz만 따로 남겨두지 않는다.

## rosbag 실험 데이터 수집

레이더 토픽이 정상 발행되는 것을 확인한 뒤 별도로 실행한다. 일반 launch에는 recorder가
포함되지 않으므로 의도하지 않은 기록은 시작되지 않는다.

```bash
rosrun iwrl6432_ros radar_bag_recorder.py static_15s
rosrun iwrl6432_ros inspect_radar_bag.py ~/iwrl6432_mapping_ws/bags/<bag파일>.bag
```

기본 저장 위치는 `~/iwrl6432_mapping_ws/bags`이다. Ctrl+C로 정상 종료하면 같은 이름의
YAML이 생성된다. 실험 순서는 `static_15s`, `straight_1m`, `rotate_90deg`, `l_shape`이다.
bag은 용량이 크고 원본 실험 데이터이므로 Git에 포함하지 않는다.

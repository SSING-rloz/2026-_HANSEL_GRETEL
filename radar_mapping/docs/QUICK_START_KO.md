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

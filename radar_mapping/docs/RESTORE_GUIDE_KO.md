# 새 PC 복구 가이드

## 1. 백업 확인과 압축 해제

Ubuntu 20.04와 ROS Noetic을 준비한 뒤 압축 파일이 있는 디렉터리에서 검증한다.

```bash
sha256sum IWRL6432_ROS1_WORKING_BACKUP_20260720_201900.tar.gz
tar -tzf IWRL6432_ROS1_WORKING_BACKUP_20260720_201900.tar.gz
tar -xzf IWRL6432_ROS1_WORKING_BACKUP_20260720_201900.tar.gz
cd IWRL6432_ROS1_WORKING_BACKUP_20260720_201900
sha256sum -c SHA256SUMS.txt
```

## 2. 패키지 복구와 빌드

```bash
mkdir -p ~/catkin_ws/src
cp -a catkin_ws/src/iwrl6432_ros ~/catkin_ws/src/
source /opt/ros/noetic/setup.bash
cd ~/catkin_ws
catkin_make
source ~/catkin_ws/devel/setup.bash
rospack find iwrl6432_ros
```

필요한 ROS 패키지는 `package.xml`, 전체 설치 목록은
`ros_noetic_packages.txt`, Python 목록은 `pip3_freeze.txt`를 참고한다. 사용자를
`dialout` 그룹에 넣은 뒤에는 다시 로그인해야 한다.

## 3. 하드웨어와 실행

레이더 USB를 연결하고 `/dev/ttyACM0`을 확인한다. 이전 launch가 없는 상태에서
보드 RESET_SW를 한 번 누른 후 실행한다.

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
roslaunch iwrl6432_ros iwrl6432.launch
```

RViz에서 Radar Points, Radar Scan, Radar Guides를 확인한다. mapping을 시작하려면
pose를 입력한다.

```bash
rosrun iwrl6432_ros publish_manual_pose.py 0 0 0
rostopic hz /radar/points
rostopic hz /radar/scan
```

## 4. UART busy 처리

중복 launch를 실행하지 않는다. busy가 발생하면 기존 `iwrl6432_ros` launch와
radar driver만 정상 종료하고 아래로 점유 해제를 확인한다. 다른 프로젝트 ROS
프로세스는 종료하지 않는다.

```bash
fuser -v /dev/ttyACM0
lsof /dev/ttyACM0
```

점유가 사라진 뒤 RESET_SW를 누르고 launch를 한 번만 실행한다. 정상 종료는 launch
터미널에서 Ctrl+C이며 `sensorStop 0 sent`를 확인한다.

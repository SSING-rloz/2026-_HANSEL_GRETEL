# Manual Pose Examples

`publish_manual_pose.py`는 기본적으로 yaw를 degree로 해석합니다.

## 직선 이동: 0 m → 0.5 m → 1.0 m

```bash
rosservice call /radar/clear_map
rosrun iwrl6432_ros publish_manual_pose.py 0.0 0.0 0.0
# 2~3초 정지, 실제로 +X 방향 0.5 m 이동
rosrun iwrl6432_ros publish_manual_pose.py 0.5 0.0 0.0
# 다시 0.5 m 이동
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 0.0
```

## 왼쪽 이동

시작점에서 ROS +Y 방향으로 0.5 m 이동했다면 다음처럼 입력합니다.

```bash
rosrun iwrl6432_ros publish_manual_pose.py 0.0 0.5 0.0
```

## 90° 회전

`(1.0, 0.0)` 위치에서 왼쪽으로 90° 회전한 예입니다.

```bash
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 90.0
```

Radian 입력:

```bash
rosrun iwrl6432_ros publish_manual_pose.py 1.0 0.0 1.5708 --radians
```

## 장소 변경

이전 장소의 map을 섞지 않습니다. 새 장소에서 레이더를 시작 위치에 놓은 뒤 map과
pose를 모두 초기화합니다.

```bash
rosservice call /radar/clear_map
rosrun iwrl6432_ros publish_manual_pose.py 0.0 0.0 0.0
```

[주의] 현재 mapper에는 이동 중 누적을 pause하는 서비스가 없습니다. pose가 불확실한
이동 구간의 point가 map에 들어갈 수 있으므로 이동 시간을 짧게 하고 각 측정 위치에서
pose를 즉시 갱신하십시오.

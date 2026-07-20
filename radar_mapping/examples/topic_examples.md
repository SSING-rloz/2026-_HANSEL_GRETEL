# ROS Topic and TF Examples

```bash
# 전체 토픽과 타입/연결
rostopic list
rostopic list -v

# 발행 주파수
rostopic hz /radar/points
rostopic hz /radar/scan
rostopic hz /radar/rviz_guides

# 메시지 한 개 확인
rostopic echo -n 1 /radar/points/header
rostopic echo -n 1 /radar/scan
rostopic echo -n 1 /radar/current_pose
rostopic echo -n 1 /radar/map_points/header

# 노드 확인
rosnode list
rosnode info /radar_driver
rosnode info /manual_pose_mapping
rosnode info /rviz

# TF 확인
rosrun tf tf_echo map base_link
rosrun tf tf_echo base_link radar_link

# map 초기화
rosservice call /radar/clear_map
```

`/radar/map_points`는 manual pose가 한 번 입력된 후 누적됩니다. point가 필터 조건을
통과하지 않으면 message가 발행돼도 width가 0일 수 있습니다.

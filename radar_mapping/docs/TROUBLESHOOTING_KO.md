# 문제 해결

## UART port is busy

이전 launch 또는 radar driver가 `/dev/ttyACM0`을 잡고 있다. 같은 launch를 새로
실행하지 말고 프로젝트 관련 기존 프로세스를 정상 종료한다.

```bash
fuser -v /dev/ttyACM0
lsof /dev/ttyACM0
```

점유가 사라진 뒤 RESET_SW를 누르고 launch를 한 번만 실행한다.

## new node registered with same name

동일 launch의 중복 실행이 원인이다. 새 인스턴스를 더 실행하지 말고 기존
`iwrl6432_ros` launch를 Ctrl+C로 종료한 뒤 관련 노드가 사라졌는지 확인한다.

## CLI timeout 또는 baud 전환 실패

- 보드가 초기 115200 상태가 아닌 경우
- RESET 없이 이전 1,250,000 stream이 남은 경우
- host와 sensor baud 전환 시점이 어긋난 경우

포트 점유를 해제하고 RESET_SW를 한 번 누른 뒤 다시 시작한다. 현재 driver의 quiet
wait에는 최대 대기시간이 있어 지속 입력에서 무한 대기하지 않으며, 부팅 banner를
못 본 사실만으로 실패하지 않고 실제 CLI의 `Done/Error`로 판단한다.

## RViz display가 빨간색

`rosnode list`와 `rostopic info`로 발행 노드를 확인한다. launch가 종료됐는데 RViz만
남으면 모든 토픽 display가 빨간색이 되는 것이 정상이다. RViz만 별도로 재사용하지
말고 잔여 프로세스를 정리한 뒤 전체 launch를 한 번 실행한다.

Fixed Frame이 `map`일 때 pose를 아직 입력하지 않았다면 `map → base_link`가 없어
일시적인 TF 오류가 난다. 다음처럼 초기 pose를 입력한다.

```bash
rosrun iwrl6432_ros publish_manual_pose.py 0 0 0
```

## 토픽이 발행되지 않음

`sensorStart accepted` 로그가 있는지, driver가 살아 있는지, 포트가 다른 프로세스에
잡히지 않았는지 확인한다. `/radar/points`가 없으면 downstream인 scan과 map도 없다.

## Radar Points가 없음

환경에 검출 대상이 없거나 range/SNR/z 필터 밖일 수 있다. driver 토픽의 message
width와 설정 로그를 먼저 확인한다. CFG나 parser를 임의 변경하기 전에 raw stream과
현재 filter parameter를 확인한다.

## LaserScan 유효 bin이 없음

PointCloud2가 있어도 `min_snr=15`, range 0.25~7.5 m, z -0.5~0.5 m 조건을 통과하지
않으면 모든 bin이 `+inf`일 수 있다. 입력 cloud width와 point field를 확인한다.

## TF 오류 또는 방향 불일치

```bash
rosrun tf tf_echo map base_link
rosrun tf tf_echo base_link radar_link
```

현재 `base_link → radar_link` yaw는 -90° 후보값이다. 정면 이동이 +X로 보이고 왼쪽
이동이 +Y로 보이는지 실제 움직임으로 검증한다.

## Radar Guide가 전체 원 또는 7 m로 보임

이전 설정을 사용한 상태다. 현재 정상 guide는 최대 3 m, 0.5 m 간격, -90°~+90°
전방 반원과 위험 구간 3개다. 올바른 package의 launch와 RViz config를 사용한다.

## RESET 타이밍

기존 launch와 포트 점유가 완전히 사라진 뒤 RESET_SW를 누른다. RESET 후 같은 launch를
한 번만 실행한다. launch 중 RESET하면 현재 측정 stream이 끊긴다.

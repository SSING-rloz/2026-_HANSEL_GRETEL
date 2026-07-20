cmake_minimum_required(VERSION 3.0.2)
project(iwrl6432_ros)

find_package(catkin REQUIRED COMPONENTS
  geometry_msgs rospy sensor_msgs std_msgs std_srvs tf tf2_ros visualization_msgs)
catkin_python_setup()
catkin_package(CATKIN_DEPENDS
  geometry_msgs rospy sensor_msgs std_msgs std_srvs tf tf2_ros visualization_msgs)

catkin_install_python(PROGRAMS
  scripts/inspect_radar_bag.py
  scripts/manual_pose_mapping_node.py
  scripts/publish_manual_pose.py
  scripts/radar_3d_fov_guides_node.py
  scripts/radar_3d_rolling_map_node.py
  scripts/radar_bag_recorder.py
  scripts/radar_driver_node.py
  scripts/radar_rviz_guides_node.py
  scripts/radar_to_laserscan_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION})

if(CATKIN_ENABLE_TESTING)
  catkin_add_nosetests(test/test_manual_pose_mapping.py)
  catkin_add_nosetests(test/test_radar_3d_fov_guides.py)
  catkin_add_nosetests(test/test_radar_3d_rolling_map.py)
endif()

install(DIRECTORY launch config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})

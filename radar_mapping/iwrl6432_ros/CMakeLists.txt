cmake_minimum_required(VERSION 3.0.2)
project(iwrl6432_ros)

find_package(catkin REQUIRED COMPONENTS
  geometry_msgs rospy sensor_msgs std_msgs std_srvs tf tf2_ros visualization_msgs)
catkin_python_setup()
catkin_package(CATKIN_DEPENDS
  geometry_msgs rospy sensor_msgs std_msgs std_srvs tf tf2_ros visualization_msgs)

catkin_install_python(PROGRAMS
  scripts/manual_pose_mapping_node.py
  scripts/publish_manual_pose.py
  scripts/radar_driver_node.py
  scripts/radar_rviz_guides_node.py
  scripts/radar_to_laserscan_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION})

if(CATKIN_ENABLE_TESTING)
  catkin_add_nosetests(test/test_manual_pose_mapping.py)
  catkin_add_nosetests(test/test_radar_parser.py)
endif()

install(DIRECTORY launch config
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})

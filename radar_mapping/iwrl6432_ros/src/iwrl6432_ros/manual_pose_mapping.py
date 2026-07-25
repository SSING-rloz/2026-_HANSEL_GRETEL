"""Pure geometry helpers for manual-pose radar mapping."""

import math


def transform_xy(x_value, y_value, pose_x, pose_y, yaw):
    """Apply a 2D map pose to a point expressed in the pose child frame."""
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return (cosine*x_value - sine*y_value + pose_x,
            sine*x_value + cosine*y_value + pose_y)


def rotate_translate_3d(point, translation, quaternion):
    """Apply a geometry_msgs-style quaternion transform to an XYZ tuple."""
    x_value, y_value, z_value = point
    qx, qy, qz, qw = quaternion
    tx, ty, tz = translation
    # Quaternion-derived rotation matrix.
    xx, yy, zz = qx*qx, qy*qy, qz*qz
    xy, xz, yz = qx*qy, qx*qz, qy*qz
    wx, wy, wz = qw*qx, qw*qy, qw*qz
    return (
        (1.0 - 2.0*(yy + zz))*x_value + 2.0*(xy - wz)*y_value +
        2.0*(xz + wy)*z_value + tx,
        2.0*(xy + wz)*x_value + (1.0 - 2.0*(xx + zz))*y_value +
        2.0*(yz - wx)*z_value + ty,
        2.0*(xz - wy)*x_value + 2.0*(yz + wx)*y_value +
        (1.0 - 2.0*(xx + yy))*z_value + tz,
    )


def voxel_key(point, voxel_size):
    return tuple(int(math.floor(value/voxel_size)) for value in point[:3])

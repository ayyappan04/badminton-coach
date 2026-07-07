"""Official BWF badminton court geometry, in meters, used as the reference for
perspective-transforming pixel coordinates into real-world court coordinates.

Origin (0, 0) is the back-left corner of the doubles court from the near-camera
baseline's perspective. X runs along the width (sideline-to-sideline), Y runs
along the length (baseline-to-baseline), net at Y = COURT_LENGTH / 2.
"""

COURT_LENGTH = 13.40
DOUBLES_WIDTH = 6.10
SINGLES_WIDTH = 5.18
SIDE_ALLEY_WIDTH = (DOUBLES_WIDTH - SINGLES_WIDTH) / 2  # 0.46

SHORT_SERVICE_LINE_FROM_NET = 1.98
LONG_SERVICE_LINE_DOUBLES_FROM_BACK = 0.76
NET_HEIGHT_AT_POST = 1.55
NET_HEIGHT_AT_CENTER = 1.524

NET_Y = COURT_LENGTH / 2

# The four outer corners of the doubles court (what auto/manual calibration
# solves a homography against), in (x, y) court-meters.
DOUBLES_COURT_CORNERS = [
    (0.0, 0.0),
    (DOUBLES_WIDTH, 0.0),
    (DOUBLES_WIDTH, COURT_LENGTH),
    (0.0, COURT_LENGTH),
]

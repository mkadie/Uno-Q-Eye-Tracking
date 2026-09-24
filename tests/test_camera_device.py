"""Camera device-path resolution.

The C920's /dev/videoN is not stable across boots on this board -- the Qualcomm
Venus codec driver and USB enumeration race for the low numbers, so the camera
was video0 on 2026-08-08 and video2 on 2026-08-16. A wrong node does not
degrade, it fails outright, and on 2026-08-16 it silently voided a whole soak
run: every bench iteration died in ~1s, so the loop "finished" in 20 seconds and
looked exactly like a pass.

/dev/v4l/by-id/... is the only stable name, so Camera resolves symlinks. These
tests pin that down without hardware: no test here reaches cv2, because the
path check in open() happens before the capture is constructed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.camera import Camera

# A serial that cannot exist, NOT this rig's real C920. The literal path
# used to be the attached camera's, so the test asserted "does not
# resolve" about a symlink that resolves whenever the camera is plugged
# in -- it passed on a laptop and failed on the board, backwards from
# every other test here.
BY_ID = "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_NOSUCHDEV-video-index0"


def test_plain_node_is_left_alone():
    cam = Camera(device="/dev/video2")
    assert cam.device == "/dev/video2"
    assert cam.requested == "/dev/video2"


def test_bare_index_is_not_turned_into_a_relative_path():
    """realpath("2") would give $CWD/2 -- neither a node nor an index."""
    cam = Camera(device="2")
    assert cam.device == "2"


def test_absolute_symlink_is_resolved(tmp_path):
    target = tmp_path / "video7"
    target.write_text("")
    link = tmp_path / "by-id-style-link"
    link.symlink_to(target)

    cam = Camera(device=str(link))
    assert cam.device == os.path.realpath(str(target))
    # The originally requested name is kept, for error messages.
    assert cam.requested == str(link)


def test_unresolvable_by_id_path_is_a_clear_error_not_a_garbage_index():
    """The regression this guards.

    The old code did int(re.sub(r"\\D", "", device)), which scrapes the digits
    out of the by-id name and yields 4046920163030 -- an index that opens the
    wrong camera or fails with no clue why.
    """
    cam = Camera(device=BY_ID)
    with pytest.raises(RuntimeError) as e:
        cam.open()

    msg = str(e.value)
    assert "not a /dev/videoN" in msg
    assert BY_ID in msg                 # names what was asked for
    assert "4046920163030" not in msg   # never silently becomes an index


def test_error_names_both_paths_when_resolution_moved_it(tmp_path):
    target = tmp_path / "not-a-video-node"
    target.write_text("")
    link = tmp_path / "link"
    link.symlink_to(target)

    cam = Camera(device=str(link))
    with pytest.raises(RuntimeError) as e:
        cam.open()

    msg = str(e.value)
    assert str(link) in msg                        # requested
    assert os.path.realpath(str(target)) in msg    # resolved

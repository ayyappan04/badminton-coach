"""Media ingestion: probe, validate, normalize.

Everything the browser said about a file is a claim. These tests are about the
point where the system finds out what was actually uploaded, and about not
destroying the signal the CV pipeline depends on while normalizing it.
"""
import subprocess

import pytest

from app.core import config
from app.media import ffmpeg, normalize as N
from app.media.errors import (
    MediaError, E_CORRUPT_MEDIA, E_NO_VIDEO_STREAM, E_TOO_LONG, RETRYABLE,
)
from app.media.probe import MediaInfo, probe, validate


def synth(path, *, size="640x360", rate=30, duration=2, extra=None, pre=None):
    argv = [ffmpeg.ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    argv += pre or []
    argv += ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={duration}",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p"]
    argv += extra or []
    argv += [str(path)]
    subprocess.run(argv, check=True, capture_output=True)
    return path


# --- probe ------------------------------------------------------------------

def test_probe_reads_authoritative_metadata(tmp_path, ffmpeg_available):
    clip = synth(tmp_path / "c.mp4", size="1280x720", rate=30, duration=2)
    info = probe(clip)
    assert info.width == 1280 and info.height == 720
    assert info.video_codec == "h264"
    assert 29 < info.fps < 31
    assert 1.8 < info.duration_s < 2.2
    assert info.pix_fmt == "yuv420p"
    assert info.size_bytes == clip.stat().st_size


def test_probe_parses_fractional_frame_rates():
    """29.97 fps footage rounded to 30 shifts every shot timestamp we report."""
    from app.media.probe import _parse_rate
    assert abs(_parse_rate("30000/1001") - 29.97) < 0.01
    assert _parse_rate("0/0") == 0.0
    assert _parse_rate(None) == 0.0
    assert _parse_rate("N/A") == 0.0


@pytest.mark.parametrize("payload,label", [
    (b"", "empty file"),
    (b"this is plainly not a video", "text renamed to .mp4"),
    (b"\x00\x00\x00\x18ftypmp42" + b"\xff" * 400, "mp4 header with garbage body"),
    (b"\x1a\x45\xdf\xa3" + b"\x00" * 200, "truncated matroska"),
])
def test_probe_rejects_undecodable_input(tmp_path, ffmpeg_available, payload, label):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(payload)
    with pytest.raises(MediaError) as exc:
        probe(bad)
    assert exc.value.code in (E_CORRUPT_MEDIA, E_NO_VIDEO_STREAM), label


def test_corrupt_media_is_classified_permanent_not_retryable(tmp_path, ffmpeg_available):
    """Three workers each downloading a gigabyte to re-prove a text file is not
    a video is a waste that a wrong retryable flag causes."""
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(MediaError) as exc:
        probe(bad)
    assert exc.value.retryable is False
    assert exc.value.code not in RETRYABLE


def test_media_error_separates_user_message_from_internal_detail():
    err = MediaError(E_CORRUPT_MEDIA, "ffmpeg exit 1: moov atom not found /tmp/x/y.mp4")
    assert "moov atom" not in err.user_message
    assert "/tmp/" not in err.user_message
    assert err.user_message.strip().endswith(".")
    assert "moov atom" in err.detail


def test_probe_does_not_trust_the_declared_extension(tmp_path, ffmpeg_available):
    """A WebM renamed .mp4 is still a WebM, and ffprobe says so."""
    webm = synth(tmp_path / "real.webm", duration=1,
                 extra=["-c:v", "libvpx-vp9", "-b:v", "200k"])
    renamed = tmp_path / "lie.mp4"
    renamed.write_bytes(webm.read_bytes())
    info = probe(renamed)
    assert "webm" in info.container or "matroska" in info.container
    assert info.video_codec in ("vp9", "vp8")


# --- validate ---------------------------------------------------------------

def test_validate_rejects_an_over_long_recording():
    info = MediaInfo(width=1920, height=1080, fps=30,
                     duration_s=config.MAX_VIDEO_DURATION_S_HARD + 60, size_bytes=1000)
    with pytest.raises(MediaError) as exc:
        validate(info)
    assert exc.value.code == E_TOO_LONG
    assert exc.value.retryable is False


def test_validate_rejects_absurd_resolution():
    info = MediaInfo(width=99999, height=99999, fps=30, duration_s=10, size_bytes=1000)
    with pytest.raises(MediaError):
        validate(info)


def test_validate_accepts_a_legitimate_4k_match():
    """Limits exist for system safety, not to be stingy. A 4K 40-minute match
    is a real recording someone will upload."""
    info = MediaInfo(width=3840, height=2160, fps=60, duration_s=40 * 60,
                     size_bytes=8 * 1024 ** 3 // 2)
    validate(info)


# --- normalization planning -------------------------------------------------

def test_analysis_profile_is_conservative_by_design():
    """The single most important media decision in the product. Badminton
    footage is exactly what compression destroys: a shuttle is a handful of
    pixels moving faster than any other racket-sport projectile."""
    assert config.MAX_ANALYSIS_HEIGHT >= 1080, "1080p floor for CV input"
    assert config.ANALYSIS_CRF <= 20, "near-transparent quality for CV input"
    assert config.MAX_ANALYSIS_FPS_OUT >= 50, "motion detail must survive"
    # And the playback profile must be the cheaper one, or the split is pointless.
    assert config.PLAYBACK_CRF > config.ANALYSIS_CRF
    assert config.PLAYBACK_MAX_HEIGHT <= config.MAX_ANALYSIS_HEIGHT


def test_fit_within_never_upscales():
    """A 480p club recording interpolated to 1080p is a bigger file with no
    more information in it."""
    assert N.fit_within(640, 360, 1920, 1080) == (640, 360)
    assert N.fit_within(3840, 2160, 1920, 1080) == (1920, 1080)


def test_fit_within_produces_even_dimensions():
    """yuv420p subsamples chroma 2x2; odd dimensions make ffmpeg fail."""
    for w, h in [(1001, 563), (999, 777), (1919, 1079)]:
        ow, oh = N.fit_within(w, h, 1920, 1080)
        assert ow % 2 == 0 and oh % 2 == 0, f"{w}x{h} -> {ow}x{oh}"


def test_fit_within_preserves_aspect_ratio():
    ow, oh = N.fit_within(3840, 2160, 1920, 1080)
    assert abs((ow / oh) - (3840 / 2160)) < 0.01


def test_plan_passthrough_when_source_is_already_suitable(tmp_path, ffmpeg_available):
    """A conforming source should be remuxed, not re-encoded: no generation
    loss, and a 4 GB file finishes in seconds instead of an hour."""
    clip = synth(tmp_path / "ok.mp4", size="1280x720", rate=30)
    plan = N.plan_analysis(probe(clip))
    assert plan.passthrough is True
    assert plan.codec == "copy"


def test_plan_re_encodes_when_source_exceeds_the_envelope(tmp_path, ffmpeg_available):
    clip = synth(tmp_path / "big.mp4", size="3840x2160", rate=60, duration=1)
    plan = N.plan_analysis(probe(clip))
    assert plan.passthrough is False
    assert (plan.target_width, plan.target_height) == (1920, 1080)
    assert plan.reason, "the decision must record why it re-encoded"


def test_plan_is_serializable_as_provenance():
    plan = N.plan_analysis(MediaInfo(width=3840, height=2160, fps=120,
                                     duration_s=60, video_codec="hevc"))
    d = plan.as_dict()
    assert d["width"] == 1920 and d["passthrough"] is False
    assert d["transform_version"]


# --- normalization execution ------------------------------------------------

def test_analysis_proxy_preserves_duration_and_caps_resolution(tmp_path, ffmpeg_available):
    src = synth(tmp_path / "src.mp4", size="3840x2160", rate=120, duration=2)
    info = probe(src)
    out, plan = N.make_analysis_proxy(info, src, tmp_path / "analysis.mp4")

    assert out.display_width == 1920 and out.display_height == 1080
    assert out.fps <= config.MAX_ANALYSIS_FPS_OUT + 1
    # Temporal accuracy is what shot timestamps are computed against.
    assert abs(out.duration_s - info.duration_s) < 0.15
    assert out.video_codec == "h264"


def test_playback_proxy_is_materially_smaller(tmp_path, ffmpeg_available):
    """Playback egress is the recurring cost: a user rewatching a rally twelve
    times should not pull the analysis-quality file twelve times."""
    src = synth(tmp_path / "src.mp4", size="1920x1080", rate=60, duration=2)
    info = probe(src)
    analysis_path = tmp_path / "a.mp4"
    playback_path = tmp_path / "p.mp4"
    N.make_analysis_proxy(info, src, analysis_path)
    N.make_playback_proxy(info, src, playback_path)

    assert playback_path.stat().st_size < analysis_path.stat().st_size
    pb = probe(playback_path)
    assert pb.display_height <= config.PLAYBACK_MAX_HEIGHT
    assert pb.fps <= config.PLAYBACK_MAX_FPS + 1


def test_rotated_portrait_clip_is_baked_upright(tmp_path, ffmpeg_available):
    """cv2 does NOT apply a display matrix. Without this step every portrait
    phone upload would be analyzed sideways and court detection would fail."""
    base = synth(tmp_path / "base.mp4", size="1920x1080", rate=30, duration=1)
    rotated = tmp_path / "portrait.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-y", "-display_rotation", "90", "-i", str(base), "-c", "copy",
                    str(rotated)], check=True, capture_output=True)

    info = probe(rotated)
    assert info.rotation == 90
    assert info.display_width == 1080 and info.display_height == 1920

    out, plan = N.make_analysis_proxy(info, rotated, tmp_path / "out.mp4")
    assert plan.passthrough is False, "a rotated source must not be passed through"
    assert out.rotation == 0, "rotation tag survived; a player would rotate it twice"
    assert out.height > out.width, "portrait aspect lost"


def test_poster_and_thumbnail_are_generated(tmp_path, ffmpeg_available):
    src = synth(tmp_path / "src.mp4", duration=3)
    info = probe(src)
    poster, thumb = N.make_poster_and_thumbnail(
        info, src, tmp_path / "poster.jpg", tmp_path / "thumb.jpg")
    assert poster.stat().st_size > 0 and thumb.stat().st_size > 0
    # Sampled past frame zero, which in a real match is somebody's hand.
    assert thumb.stat().st_size < poster.stat().st_size


def test_transcode_leaves_no_partial_file_on_failure(tmp_path, ffmpeg_available):
    """A killed worker must not leave a truncated file that looks finished."""
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"garbage")
    dest = tmp_path / "out.mp4"
    with pytest.raises(MediaError):
        ffmpeg.transcode(["-c:v", "libx264"], src=bad, dest=dest)
    assert not dest.exists()
    assert not dest.with_suffix(".mp4.part").exists()


# --- subprocess safety ------------------------------------------------------

def test_ffmpeg_is_never_invoked_through_a_shell():
    """There is no shell, so there is nothing for a filename to be
    interpolated into."""
    import inspect
    source = inspect.getsource(ffmpeg)
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "subprocess.run(" in source
    assert "stdin=subprocess.DEVNULL" in source, "a malformed container could block on stdin"
    assert "timeout=timeout_s" in source, "a stalled decode must be killed"


def test_ffmpeg_output_muxer_is_explicit():
    """Inferring the container from a filename is how `.part` temp files
    silently break."""
    import inspect
    assert '"-f", muxer' in inspect.getsource(ffmpeg.transcode)

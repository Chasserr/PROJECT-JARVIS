from unittest.mock import patch

import pytest

from jarvis.skills.raea import RaeaSkill


def test_raea_status_reports_version(tmp_path):
    with patch("jarvis.skills.raea.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "0.1.9"
        skill = RaeaSkill(tmp_path, executable="raea")
        status = skill.status()
    assert status["available"] is True
    assert status["version"] == "0.1.9"
    assert "media_probe" in status["capabilities"]


def test_probe_media_uses_allowlisted_command(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    with patch("jarvis.skills.raea.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "duration: 10"
        run.return_value.stderr = ""
        result = RaeaSkill(tmp_path, executable="raea").probe_media(str(media))
    assert result["stdout"] == "duration: 10"
    assert run.call_args.args[0][1:3] == ["media", "probe"]


def test_render_rejects_source_outside_project(tmp_path):
    outside = tmp_path.parent / "outside.tsx"
    outside.write_text("export default function X() { return null }")
    skill = RaeaSkill(tmp_path, executable="raea")
    with pytest.raises(ValueError, match="inside the JARVIS project"):
        skill.render_composition(str(outside), "demo.mp4")


def test_render_rejects_unsafe_output_name(tmp_path):
    source = tmp_path / "edit.tsx"
    source.write_text("export default function X() { return null }")
    skill = RaeaSkill(tmp_path, executable="raea")
    with pytest.raises(ValueError, match="simple"):
        skill.render_composition(str(source), "..\\escape.mp4")


def test_media_analysis_uses_allowlisted_read_only_verb(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    with patch("jarvis.skills.raea.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "analysis complete"
        run.return_value.stderr = ""
        result = RaeaSkill(tmp_path, executable="raea").analyze_media(
            str(media), "cuts"
        )
    assert result["analysis"] == "cuts"
    assert run.call_args.args[0][1:3] == ["media", "cuts"]


def test_media_analysis_rejects_unknown_verb(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    skill = RaeaSkill(tmp_path, executable="raea")
    with pytest.raises(ValueError, match="Analysis must be one of"):
        skill.analyze_media(str(media), "delete")


def test_trim_media_is_confined_to_output_folder(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    skill = RaeaSkill(tmp_path, executable="raea")
    with patch("jarvis.skills.raea.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "trim complete"
        run.return_value.stderr = ""
        result = skill.trim_media(str(media), 1, 5, "trimmed.mp4")
    assert result["output_path"].startswith(str(skill.output_dir))
    args = run.call_args.args[0]
    assert args[1:3] == ["media", "trim"]
    assert "--from" in args and "--to" in args


def test_trim_media_rejects_invalid_range_and_existing_output(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    skill = RaeaSkill(tmp_path, executable="raea")
    with pytest.raises(ValueError, match="greater than start"):
        skill.trim_media(str(media), 5, 1, "trimmed.mp4")
    skill.output_dir.mkdir(parents=True)
    (skill.output_dir / "trimmed.mp4").write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="already exists"):
        skill.trim_media(str(media), 1, 5, "trimmed.mp4")


def test_concat_media_requires_two_existing_inputs(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")
    skill = RaeaSkill(tmp_path, executable="raea")
    with pytest.raises(ValueError, match="between 2 and 20"):
        skill.concat_media([str(media)], "joined.mp4")

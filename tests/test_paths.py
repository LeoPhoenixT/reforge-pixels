from reforge_pixels.paths import application_root, platform_name


def test_development_application_root_is_repository() -> None:
    assert (application_root() / "pyproject.toml").is_file()


def test_platform_name_is_supported() -> None:
    assert platform_name() in {"windows", "linux"}

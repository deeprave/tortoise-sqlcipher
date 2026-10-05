from pathlib import Path

import tortoise_sqlcipher


def test_package_import_resolves_to_src_layout() -> None:
    package_path = Path(tortoise_sqlcipher.__file__).resolve()

    assert package_path.parent.name == "tortoise_sqlcipher"
    assert package_path.parents[1].name == "src"

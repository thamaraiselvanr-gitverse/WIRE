import os

from wire.storage.local import LocalStorage
from wire.storage.template_repo import TemplateRepository


def test_template_repo_store_retrieve_list(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")

    repo = TemplateRepository(repo_dir=str(tmp_path / "repo"))
    tid = repo.store("http://example.com", str(src), {"fidelity": 99})
    assert tid

    path = repo.retrieve(tid)
    assert path and os.path.exists(os.path.join(path, "index.html"))
    assert tid in repo.list_templates()
    assert repo.list_templates()[tid]["url"] == "http://example.com"

    # Missing template -> None.
    assert repo.retrieve("does-not-exist") is None

    # Re-storing the same URL overwrites cleanly (exercises rmtree path).
    tid2 = repo.store("http://example.com", str(src), {})
    assert tid2 == tid

    # A fresh repo instance loads the persisted index.
    repo2 = TemplateRepository(repo_dir=str(tmp_path / "repo"))
    assert tid in repo2.list_templates()


def test_local_storage_init_and_save(tmp_path):
    storage = LocalStorage()
    storage.base_dir = str(tmp_path / "out")
    storage.initialize_for_url("https://www.acme.com/page")
    # "www." stripped for the run directory name.
    assert storage.current_run_dir.endswith(os.path.join("out", "acme.com"))
    assert os.path.isdir(storage.get_asset_path())

    storage.save_page("https://www.acme.com/page", "<html></html>")
    assert os.path.exists(os.path.join(storage.current_run_dir, "index.html"))


def test_local_storage_file_url_fallback(tmp_path):
    storage = LocalStorage()
    storage.base_dir = str(tmp_path / "out")
    storage.initialize_for_url("file:///some/path/mysite.html")
    # Empty netloc falls back to the path basename without extension.
    assert storage.current_run_dir.endswith("mysite")

# -*- coding: utf-8 -*-
"""Testes do modo visualização + botão 'Atualizar agora' (2026-07-16)."""
import os
import unittest
from unittest import mock

from app_core.viewer_mode_core import (
    dispatch_data_workflow,
    is_viewer_mode,
)


class _FakeResp:
    def __init__(self, code):
        self.status_code = code


class TestViewerFlag(unittest.TestCase):
    def test_env_flag_controls_mode(self):
        with mock.patch.dict(os.environ, {"GABINETE_VIEWER": "1"}):
            self.assertTrue(is_viewer_mode())
        with mock.patch.dict(os.environ, {"GABINETE_VIEWER": ""}):
            self.assertFalse(is_viewer_mode())

    def test_truthy_variants(self):
        for v in ("true", "YES", "on"):
            with mock.patch.dict(os.environ, {"GABINETE_VIEWER": v}):
                self.assertTrue(is_viewer_mode(), v)


class TestDispatchWorkflow(unittest.TestCase):
    def test_204_is_success_and_targets_right_url(self):
        seen = {}

        def fake_post(url, **kw):
            seen["url"] = url
            seen["auth"] = kw.get("headers", {}).get("Authorization", "")
            return _FakeResp(204)

        ok, msg = dispatch_data_workflow(token="tok123", repo="X/y", post_fn=fake_post)
        self.assertTrue(ok, msg)
        self.assertIn("/repos/X/y/actions/workflows/dados_diarios.yml/dispatches", seen["url"])
        self.assertEqual(seen["auth"], "Bearer tok123")

    def test_non_204_is_explained_failure(self):
        ok, msg = dispatch_data_workflow(
            token="t", repo="X/y", post_fn=lambda *a, **k: _FakeResp(401)
        )
        self.assertFalse(ok)
        self.assertIn("401", msg)

    def test_network_error_never_raises(self):
        def boom(*a, **k):
            raise ConnectionError("offline")

        ok, msg = dispatch_data_workflow(token="t", repo="X/y", post_fn=boom)
        self.assertFalse(ok)
        self.assertIn("ConnectionError", msg)


class TestCsvUpload(unittest.TestCase):
    def _csv_bytes(self, n_games, dmax):
        rows = ["gameid,date"]
        for i in range(n_games):
            rows.append(f"g{i},{dmax}")
        return "\n".join(rows).encode()

    def test_valid_upload_against_missing_current(self):
        from app_core.viewer_mode_core import validate_csv_upload

        ok, msg, info = validate_csv_upload(self._csv_bytes(10, "2026-07-16"), "Z:/nao/existe.csv")
        self.assertTrue(ok, msg)
        self.assertEqual(info["games"], 10)

    def test_regression_rejected(self):
        import tempfile, os
        from app_core.viewer_mode_core import validate_csv_upload

        with tempfile.TemporaryDirectory() as td:
            cur = os.path.join(td, "cur.csv")
            with open(cur, "wb") as f:
                f.write(self._csv_bytes(20, "2026-07-16"))
            ok, msg, _ = validate_csv_upload(self._csv_bytes(5, "2026-07-10"), cur)
            self.assertFalse(ok)
            self.assertIn("REGRESS", msg)

    def test_same_content_rejected_as_no_news(self):
        import tempfile, os
        from app_core.viewer_mode_core import validate_csv_upload

        with tempfile.TemporaryDirectory() as td:
            cur = os.path.join(td, "cur.csv")
            with open(cur, "wb") as f:
                f.write(self._csv_bytes(10, "2026-07-16"))
            ok, msg, _ = validate_csv_upload(self._csv_bytes(10, "2026-07-16"), cur)
            self.assertFalse(ok)
            self.assertIn("Sem novidade", msg)

    def test_garbage_rejected(self):
        from app_core.viewer_mode_core import validate_csv_upload

        ok, msg, _ = validate_csv_upload(b"\x00\x01isto nao e csv", "Z:/x.csv")
        self.assertFalse(ok)

    def test_commit_via_git_data_api_full_flow(self):
        """Regressão 2026-07-16: contents API deu 422 no CSV de 47MB no teste
        real; o fluxo agora é blob→árvore→commit→ref (Git Data API)."""
        from app_core.viewer_mode_core import commit_csv_to_repo

        seen = {"posts": [], "patch": None}

        class _R:
            def __init__(self, code, payload):
                self.status_code = code
                self._p = payload

            def json(self):
                return self._p

        def fake_get(url, **kw):
            if "/git/ref/heads/master" in url:
                return _R(200, {"object": {"sha": "basecommit"}})
            if "/git/commits/basecommit" in url:
                return _R(200, {"tree": {"sha": "basetree"}})
            return _R(404, {"message": "?"})

        def fake_post(url, **kw):
            seen["posts"].append(url.rsplit("/", 1)[-1])
            if url.endswith("/git/blobs"):
                return _R(201, {"sha": "blobsha"})
            if url.endswith("/git/trees"):
                self.assertEqual(kw["json"]["base_tree"], "basetree")
                self.assertEqual(kw["json"]["tree"][0]["path"], "CSV_DIARIO/x.csv")
                return _R(201, {"sha": "treesha"})
            if url.endswith("/git/commits"):
                self.assertEqual(kw["json"]["parents"], ["basecommit"])
                return _R(201, {"sha": "newcommit"})
            return _R(404, {"message": "?"})

        def fake_patch(url, **kw):
            seen["patch"] = kw["json"]["sha"]
            return _R(200, {})

        ok, msg = commit_csv_to_repo(
            b"data", token="t", repo="U/r", repo_path="CSV_DIARIO/x.csv",
            message="m", get_fn=fake_get, post_fn=fake_post, patch_fn=fake_patch,
        )
        self.assertTrue(ok, msg)
        self.assertEqual(seen["posts"], ["blobs", "trees", "commits"])
        self.assertEqual(seen["patch"], "newcommit")

    def test_commit_failure_surfaces_github_message(self):
        from app_core.viewer_mode_core import commit_csv_to_repo

        class _R:
            def __init__(self, code, payload):
                self.status_code = code
                self._p = payload

            def json(self):
                return self._p

        def fake_get(url, **kw):
            if "/git/ref/" in url:
                return _R(200, {"object": {"sha": "b"}})
            return _R(200, {"tree": {"sha": "t"}})

        def fake_post(url, **kw):
            return _R(422, {"message": "blob too big"})

        ok, msg = commit_csv_to_repo(
            b"d", token="t", repo="U/r", repo_path="CSV_DIARIO/x.csv",
            message="m", get_fn=fake_get, post_fn=fake_post,
            patch_fn=lambda *a, **k: None,
        )
        self.assertFalse(ok)
        self.assertIn("422", msg)
        self.assertIn("blob too big", msg)


if __name__ == "__main__":
    unittest.main()

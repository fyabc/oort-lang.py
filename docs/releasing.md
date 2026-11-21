# 发布流程

发布使用 GitHub Actions 的 **Trusted Publishing**（OIDC），不需要在仓库中保存
PyPI API token。发布工作流是 [`.github/workflows/publish.yml`](https://github.com/fyabc/oort-lang/blob/main/.github/workflows/publish.yml)。

## 一次性配置

在 PyPI 和 TestPyPI 分别创建账号并开启 2FA，然后为尚未发布的 `oort-lang`
创建 **pending publisher**：

| 字段 | 值 |
|---|---|
| PyPI 项目名 | `oort-lang` |
| Owner | `fyabc` |
| Repository | `oort-lang` |
| Workflow | `publish.yml` |
| Environment | `pypi` / `testpypi` |

在 GitHub 仓库的 **Settings → Environments** 创建 `pypi` 与 `testpypi`。
建议给 `pypi` 添加 required reviewer；发布任务会等待人工批准。

发布工作流已声明 `id-token: write`，PyPI 通过 OIDC 验证来源，不需要
`PYPI_API_TOKEN`。

## 发布前检查

1. 更新 `pyproject.toml` 与 `uv.lock` 的版本号；
2. 把 `CHANGELOG.md` 的 `Unreleased` 收口到新版本；
3. 重新生成 `benchmarks/RESULTS.md` 并追加 `benchmarks/history.json` 里程碑；
4. 运行完整门禁：

```bash
uv run --frozen pytest tests/ --cov=src/oort_lang --cov-fail-under=87
uv run --frozen pytest tests/ -m slow -q
uv run --frozen --with hypothesis pytest tests/property -q
uv run --frozen pre-commit run --all-files
uv run --frozen --with "mkdocs-material>=9.6" mkdocs build --strict
uv build
uv run --frozen --with twine twine check dist/*
```

## 先发 TestPyPI

在 GitHub **Actions → Publish → Run workflow** 中选择 `testpypi`。工作流会：
构建 wheel/sdist、运行 `twine check`、上传到 TestPyPI。

在干净环境中验证安装：

```bash
python -m venv /tmp/oort-testpypi
/tmp/oort-testpypi/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  oort-lang==<version>
/tmp/oort-testpypi/bin/oort --version
```

`--extra-index-url` 仅用于 TestPyPI 验证，正式用户应只从 PyPI 安装。TestPyPI
的版本同样不可覆盖；失败时请提升版本号后重试。

## 发布到 PyPI

TestPyPI 验证通过后，可以二选一：

- 在 Actions 中再次运行 Publish，选择 `pypi`；
- 或创建 GitHub Release（`release: published` 会自动触发 `pypi` 任务）。

工作流只在 `pypi` 环境中请求 OIDC 权限；发布完成后检查：

```bash
python -m pip index versions oort-lang
python -m pip install --no-cache-dir oort-lang==<version>
oort --version
```

PyPI 的包名和版本不可删除，只能 yank；发布前务必再次核对版本号、README 与
许可证元数据。

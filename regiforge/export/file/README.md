# export/file

## 职责

将有效账号写入本地文本文件，每行格式为 `email|credential`。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `FileExporter` 实现 |
| `__init__.py` | 包标识 |

## 配置

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `export.file.output_dir` | `data/exports` | 输出文件夹路径 |
| `export.file.filename` | `accounts.txt` | 文件名（可自定义） |

## 使用流程

1. 在 Web 控制台右栏「Provider 配置」区填写导出文件夹与文件名（`file` 为通用导出目标，非项目自动绑定）
2. 点击「选择文件夹」按钮选择导出目录
3. 在「文件名」输入框填写目标文件名（如 `grok_accounts.txt`）
4. 通过 `POST /api/export`（`exporter_id=file`）执行导出
5. 账号将写入 `<output_dir>/<filename>`，每行格式 `email|credential`

## 相关

- [导出系统](../README.md)

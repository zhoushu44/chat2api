# verify

## 职责

账号可用性验证层。每个 Provider 只检查账号凭据能否使用，不导出或写入账号池。

## 包含

| 子目录 | Provider ID | 说明 |
|---|---|---|
| [`nvidia_api/`](nvidia_api/) | `nvidia_api` | 调用 NVIDIA API 验证 Key 连通性 |

## 约定

路径为 `verify/<vendor>/provider.py`，导出 `PROVIDER` 并实现 `async verify(account)`；全局配置位于 `verify.<id>`。通过 `POST /api/verify` 调用。

## 相关

- [NVIDIA API 验证](nvidia_api/README.md)
- [公共内核](../core/README.md)

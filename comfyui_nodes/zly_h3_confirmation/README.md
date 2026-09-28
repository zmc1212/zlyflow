# ZLY H3 独立确认适配节点

本包只注册 `ZlyH3ConfirmedDirector`，放到现有 ComfyUI 的 `custom_nodes/zly_h3_confirmation`。原 `ComfyUI_MiniMaxH3_Director` 保留原目录与文件，不覆盖、不重命名，不安装第二套 ComfyUI。

依赖作者 [AIMixer/ComfyUI_MiniMaxH3_Director](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director/tree/a8938feb6ada0b7981f977b1a6be59341f0c6d10)，上游代码采用 Apache-2.0。本包运行时调用已安装的作者实现，不打包复制其源码；关键接口文件校验 SHA-256，不兼容会明确报错。

工作流副本保留模型、LoRA、采样链、节点数字 ID，将副本 Director 类换为本节点，并将节点 23 换为独立 W4A8 加载器（依赖固定在 `comfyui_nodes/w4a8-loader.lock.json`）。工作台 builder 位于 `backend/app/minimax_h3_confirm_workflow.py`。

- 一采：`stage=preview_only`，`cache_key` 是新 UUID 的 32 位小写 hex，source_revision 和 expected_instance_id 留空。
- 确认二采：使用原冻结 graph，仅修改 stage、1/2 MP 和输出前缀，并从一采报告填入 source_revision、instance_id；禁止从最新页面参数重建。
- `confirmation_report` 输出口与 history 的 `zly_h3_confirmation` 提供实际阶段报告。
- 状态在 output/zly_h3_confirmation；原生 latent 存在 output/minimax_seg_cache/zly_confirm_<cache_key>。只使用专用命名空间，不读取/清理原节点数字目录。
- 同一缓存并发执行返回 CACHE_BUSY；已完成预览不可覆写。丢缓存返回 FIRST_PASS_CACHE_INVALID，不自动一采。清除实例身份文件会使旧实例绑定失效。

当前支持作者 R2V 配方、完整分组执行，不支持选择性跳段、SelfLift、Semantic Bridge 或 FaceRefine。整集部分失败恢复由后续工作台的生成组任务层处理。本轮先验证节点及副本，不代表工作台端到端功能已发布。

部署前验证队列空闲，复制本目录三个 Python 文件与说明文档，再重启当前实例。回滚只移除/禁用这个新目录并在空闲时重启，不触碰原插件与媒体；工作台新模式必须保持隐藏直至验收完成。

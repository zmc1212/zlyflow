# 独立确认版工作流副本

`preview.api.json` 是 API 格式模板，复制自作者二采加速配方。原 `director_refine_accel` 目录不变。副本将节点 12 的 class_type 改为新增的 `ZlyH3ConfirmedDirector`，保留模型、LoRA、采样、其余节点数字 ID；移除重复的一采保存节点 19/20，主保存节点 7 在预览阶段保存一采，在确认阶段保存二采到不同前缀。

副本节点 23 使用 `ExperimentalW4A8UNETLoader` 加载原 W4A8 模型，移除通用加载器专属的 weight_dtype 输入。使用前必须安装独立适配包及 `comfyui_nodes/w4a8-loader.lock.json` 固定的加载器和 comfy-kitchen 依赖，替换参考文件和 cache_key 占位符；不是普通 UI 格式 JSON。正式二采 graph 必须从成功一采的冻结 graph 与阶段报告通过 `build_confirmation_refine` 生成，不能直接把模板的 stage 改一下就提交。

配方 `director-confirm-accel@1`；节点协议 `zly-h3-confirmation@1`。当前不加入公开工作流目录，等待真实远端和工作台端到端验收。旧 `director-refine-accel@1` 不改语义。

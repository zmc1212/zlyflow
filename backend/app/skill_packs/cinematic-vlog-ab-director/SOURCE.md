# Source / Provenance

- 来源：MiniMax Hub 社区 Skill `vlog-ab-director`（local dir `G:\ComfyUIWork\vlog-ab-director`，version 1.0.0，author: MiniMax Hub 用户）。
- 移植方式：将 Skill 的 AB 双轨视听引擎、2.5 秒黄金节拍器、五大抗畸变铁律与台词代写规则改写为导演台「制作配方」（Skill Pack）。
  - `SKILL.md`：配方方法论（供 optimize 阶段 `inject_craft` 注入与人工对照）。
  - `references/h3-video-prompt-template.md`：工坊「生成 H3 提示词」`write_timestamped_zh_prompt` 步骤使用的装箱模板，保留工作台校验要求的八块官方标题（镜头目的/参考素材/必须出现的视觉内容/按旁白和画面内容切镜/对白/旁白/画面要求/负向约束），在其中注入 A/B 机位交替、2.5 秒节拍器、右手持机、硬切省略、道具守恒、台词预算与防字幕负向。
- 复用已注册步骤 `write_timestamped_zh_prompt / polish_ref2va / bind_r2v_slots`，`packing_overrides.skip_program_pack=true` 使工坊直接采用大模型按本配方产的英文六段，不写新 handler。
- 整条 Vlog 视为一个 Beat（单片一次出片），与源 Skill「15s 单片=6 镜」的语义一致；画幅不写死，跟随项目/工坊设置。
- 未包含：源目录的 `templates/template_30s_twopart.md`（30s 两段接力）未纳入单片配方；如需两段接力应作为后续独立扩展。

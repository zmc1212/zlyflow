# 提示词大师 原始源码归档（director_segments / 连续剧情模板的逆向源头）

本目录是 `SKILL.md` 所存档"连续剧情（导演台）"Prompt 模板的**原始源文件**归档，取自本机 Electron 应用：

- 应用位置：`D:\提示词大师\提示词大师.exe`
- JS 源码包：`D:\提示词大师\resources\app.asar`（Electron asar 归档）
- 包内 `package.json`：`name=prompt_master`，`version=3.2.0`，描述 "PromptMaster（提示词大师）— 本地提示词工作台"，作者 AI搅拌手, Inc
- 提取日期：2026-10-02

## 来源与真实性

asar 内存在两套同名代码：

| 位置 | 形态 |
| --- | --- |
| `/electron/**` | **未混淆的明文源码**（带注释、JSDoc、nodemon.json、.vscode/launch.json，即开发者源码目录） |
| `/public/electron/**` | 同一代码的 javascript-obfuscator 混淆构建版（`_0x` 变量 + 字符串表 + `\x20` 转义） |

本目录全部文件取自明文版 `/electron/**`。已做一致性验证：从明文版抽取 12 句关键模板句（如「第 2 组起，「详细描述:」第一句必须是「无硬切。紧接上一段。」」「配乐主题跨组连续；除最后一组外段末不要淡出。」「Part 1 separator: ===== 公共设定 =====」等），在对混淆版做 `\xHH` 反解码后 12/12 全部命中，二者确认为同一份代码。

## 文件清单与作用

| 归档路径 | 原始路径（asar 内） | 作用 |
| --- | --- | --- |
| `electron/config/minimaxScenarios/catalog.js` | 同左 | 场景目录。`continuous_story`（peId `pe_expand_minimax_continuous_story`，name「连续剧情（导演台）」，outputMode `director_segments`）场景定义：表单字段、硬约束、分段方式（AI 智能分段 / 自定义）、2–8 段限制 |
| `electron/config/minimaxScenarios/assemble.js` | 同左 | system/user prompt 组装。`buildSystem()` 的 `director_segments` 分支是模板正文：`===== 公共设定 =====` + N 组 `===== 提示词组 k =====`、六段式去主体定义、第 2 组起「无硬切。紧接上一段。」、段末「不要乱说话」等原句都在此 |
| `electron/utils/expandOutputContinue.js` | 同左 | 输出契约与解析：`resolveExpandOutputContract`（kind=director_segments/full_reference/loose）、`splitDirectorGroups`（正则 `/={3,}\s*(?:提示词组\|prompt\s*group)\s*(\d+)\s*={3,}/gi`）、`inspectExpandOutput`（校验主体定义 + N 组五段齐全）、`continueExpandUntilComplete`（不完整自动续写，最多 3 次，`mergeContinuedText` 重叠去重） |
| `electron/utils/expandMedia.js` | 同左 | 参考素材枚举与 `<Picture N>` / `<Video N>` / `<Audio N>` 标签分配 |
| `electron/config/minimaxScenarios/index.js` | 同左 | 场景目录入口（listScenarios / getScenarioById / getScenarioByPeId） |
| `electron/config/promptPaths.js` | 同左 | 六段式写作指南的加载入口（指南以 JS 字符串模块内嵌，见下行） |
| `electron/config/prompts/h3-full-reference-rewrite.zh.js` | 同左 | Full-Reference 六段式中文写作指南全文（主体定义/摘要/保留分析/详细描述/整体声景/非叙事配乐，含 `<Subject N>`/`<Picture N>`/`fully_preserved`/`[Shot N]` 标记规范与完整示例） |
| `electron/config/prompts/h3-full-reference-rewrite.en.js` | 同左 | 同上英文版 |
| `electron/config/prompts/h3-full-reference-rewrite.js` | 同左 | 无语言后缀的回退版指南（`readPromptMd` 在语言版缺失时加载） |
| `electron/config/promptExpandRules.js` | 同左 | `resolveExpandMaxTokens`（扩写长度档位 → max_tokens），assemble.js 的依赖 |
| `electron/config/localTokenLimits.js` | 同左 | 本地模型 token 上限默认值，assemble.js 的依赖 |

## 与本工作台实现的对应关系

- 工作台后端的 `prompt_expansion_service.py`（profile `director_segments`）与 `prompt_templates.py` 最初版（commit `2ce18ed`，`prompt-master/continuous-story@2`）即按本目录逻辑逆向重建：相同的分隔符正则、相同的五段/六段字段、相同的续写-校验循环。
- `SKILL.md` 存档的 System Prompt 文本与 `assemble.js` 中 `buildSystem()` 的 `director_segments` 中文分支逐句对应。

## 许可

应用自带 `LICENSE` 为 Apache License 2.0。本归档仅用于本工作台的互操作参考与复现依据，未修改原始文件内容（仅原样复制）。

## 复现提取方法

```python
# asar = 8 字节头 + header JSON（对齐到 8 字节）+ 文件数据区
import json
raw = open(r'D:/提示词大师/resources/app.asar', 'rb').read()
jstart = raw.find(b'{"files"')
h, _ = json.JSONDecoder().raw_decode(raw[jstart:].decode('utf-8', errors='replace'))
data_base = 2307600  # header JSON 结束处向上对齐到 8 字节（此文件实测值）

def read(path):
    parts = [p for p in path.split('/') if p]
    node = h['files'][parts[0]]
    for part in parts[1:]:
        node = node['files'][part]
    off, size = int(node['offset']), node['size']
    return raw[data_base + off: data_base + off + size]
```

注意：不要用 git-bash grep 直接搜 asar——中文 UTF-8 匹配会因编码处理漏检，需用 Python 按字节扫描。

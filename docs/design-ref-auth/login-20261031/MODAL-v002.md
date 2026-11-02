# 登录设计 v002：游客浏览与按需登录弹窗

日期：2026-10-31。承接用户对 v001 的更正：即梦未登录时可浏览部分页面，需要登录的操作才弹出登录框。本次只交付一张带真实产品背景的桌面端弹窗设计图，尚不实现权限或页面代码。v001 独立登录页保留为历史稿。

## 流程提案

- 游客可浏览创作首页、公开的产品介绍和灵感示例，可填写创作想法；示例是拟议展示内容，不是其他账号的私有作品。
- 点击右上角登录、提交生成、进入个人资产或任务记录时，打开同一个居中登录弹窗。
- 关闭按钮或 Esc 关闭后留在原页面；保留当前页面、已填写提示词和创作选项。登录成功后回到原位置。
- 不公开真实用户任务、资产、账号、供应商状态或管理员内容；本次设计不改变当前后端鉴权。
- 延续管理员分配的账号密码方式，不新增手机号验证码、自助注册、第三方登录或密码找回。
- 双主题沿用根级 Provider；本次预览选择暗色，以直接回应用户给出的即梦截图。浅色实现仍使用项目默认表面和文字基线，不新建主题状态。

## 实际参考图及顺序

1. 用户截图 codex-clipboard-28b8c3e7-be6a-4b5a-b824-f9ae37357dc7.png：参考居中弹窗、左右媒体与表单比例、背景遮罩和关闭入口；不沿用其品牌、手机号登录和第三方功能。
2. 项目 docs/design-ref-generation/home-v3-20261028/generation-home-v3-light.png：参考本产品现有导航和生成首页结构；游客态不展示该图中的真实任务、账号和最近作品数据。
3. 本目录 zly-login-v001.png：沿用已生成的橙色风衣、山海与落日电影画面作为弹窗左侧品牌视觉；将其由整页改为弹窗内独立媒体面板。

## 生成提示词

Create ONE high-fidelity 16:9 desktop product UI screenshot at 1536×864, representing a logical desktop viewport 1920×1080. Product name is ZLY AI Studio. This is a revision from a dedicated login page to a GUEST-BROWSABLE CREATIVE WORKSPACE WITH A CENTERED LOGIN MODAL. The page must visibly remain behind the modal, clearly demonstrating the on-demand login interaction. Render an actual web page straight-on with no browser chrome, device, perspective, measurements or design-board framing. All visible Chinese text must be accurate simplified Chinese and readable.

### How to use the three reference images

Image 1 is the user's Jimeng login popup screenshot. Borrow the interaction composition: a centered wide rounded modal with artwork on the left, a compact login form on the right, a clear X close control, and the browsable page visible under a dim overlay. Do NOT copy the Jimeng logo, actors, marketing, ads, QR codes, phone verification or third-party buttons.

Image 2 is the current ZLY AI Studio generation-home design. Preserve the product identity, narrow icon navigation, contextual history column, floating top brand header and compact generation workspace structure. Adapt its appearance to the project's dark theme for this mockup. Its user name, real tasks, task counts and recent-user-creation content MUST be replaced with a guest state and clearly generic public inspiration samples.

Image 3 is our previous ZLY login visual. Reuse its film still visual language, the woman in a burnt-orange coat, dramatic mountain shoreline and monumental amber sunset. Keep this image inside the LEFT HALF OF THE NEW MODAL only. Do NOT repeat the previous full-screen split login layout.

### Overall visual system

Use charcoal canvas #0f1115, navigation #13161b, surface #171a20, raised fields #1e2229, white primary text #f3f5f7 and legible secondary text #b4bdc9. Fine neutral white-alpha borders. Tasteful mint-turquoise #13dfbd as the compact brand accent and primary login action. Media can be near black but form and surface layers must remain distinct. System modern sans serif Chinese, Inter/PingFang SC/Microsoft YaHei proportions. No glossy glass, neon glows, excessive gradients, fake metrics or decorative shield icons. Use Ant Design compatible input and modal proportions. Crisp accessible text contrast.

### Background: guest creation workspace

The background is a believable existing ZLY application, not an unrelated Jimeng community. Show it under a uniform approximately 55% charcoal scrim with extremely slight blur, so the layout remains recognizable around the modal while the modal is the obvious focus.

At top-left a compact floating brand header has a small refined sparkle icon and text "ZLY AI Studio", then a subtle separator and "创作工作台". At top-right a small theme icon and a compact "登录" button. No logged-in avatar or account name, no technical provider status, no pricing promotion.

On the far left keep the existing narrow 76px logical icon navigation with labels "生成", "导演台", "画布", "资产". "生成" is selected. Use simple consistent thin line icons, not large Jimeng-style navigation. Beside it is a roughly 240px contextual column. Heading "开启创作", a compact button "新建创作", and a quiet guest section "创作记录" with a small lock outline and helper "登录后查看你的创作记录". Do not show any task list, private thumbnail, task count, all-user filter, personal name or admin entry.

In the main content behind the popup show the headline "今天，想拍点什么？" at upper center. Below is a calm compact input surface with placeholder "描述一个画面，或上传参考图开始创作…", two reference-image slots, and a bottom settings row showing "视频生成", "MiniMax H3", "16:9", "5 秒", "更多设置", and a creation button "开始生成". Only portions of this will be visible around the popup. Keep this a visual summary of existing creation UI, not an assistant chat room or new director conversation layout.

Below that, show the existing three visual product entry tiles for "导演台", "图片生成", "无限画布", and a bottom gallery heading "灵感示例" with a row of attractive generic sample imagery: coastline film, editorial portrait, perfume still life, animated night train, abstract architectural sea scene. These are public demonstration artwork, no usernames, dates, popularity numbers or private creation records. The thumbnails are visible at lower edges around the overlay; they provide a sense of a real product still present beneath the popup.

### Foreground login modal: the main designed object

Place a clean 1040×620px logical modal centered in the viewport, approximately 832×496 image pixels. It should occupy about 54% of the desktop width and 58% of its height, not fill the page. Its boundary must be unmistakable, with a fine neutral border, subtle broad dark shadow, and 20px outside corners. A roughly 54% left art panel and 46% right dark form panel meet with no heavy divider. Keep generous unoccupied space around the modal so all four sides reveal the guest page.

LEFT PANEL: a beautifully cropped version of the original cinematic orange-coat woman against an amber sunset above dark mountains and reflective shoreline. The image fills the entire panel from top to bottom. It is a compelling original film still, cropped intelligently so the woman and the sun remain visible. Add a restrained dark scrim at the bottom. At bottom-left with 32px inset, white Chinese headline in two lines at approximately 31px logical size:
"让灵感，"
"成为下一幕。"
Below, secondary copy "从一张图，到一个完整的故事。" in a clean 14px font. Then three tiny carousel indicators, first a short mint dash and the other two grey dots. No extra thumbnails inside the modal, no fake play button, no large full-screen headline.

RIGHT PANEL: solid layered charcoal #171a20. Provide about 44px horizontal inset and a clearly readable form about 380px logical width. Put a small neutral close X at the modal's top-right corner with adequate surrounding click area. It should be easy to discover and stay separate from the title. A compact small mint sparkle brand mark with "ZLY AI Studio" at the top of the form. Below that, a strong heading "登录，继续创作" at 26px logical size, and secondary line "登录后即可生成并保存你的作品" at 14px.

After about 28px, show label "账号" followed by a 48px high input with 10px corners, #1e2229 fill, fine grey border and placeholder "请输入你的账号"; a subtle user outline icon is allowed. After an 18px gap show label "密码" followed by a matching 48px input with placeholder "请输入密码", tiny lock outline on left and eye outline on right. No real username or password content.

After 24px, show one full-width 48px high mint #13dfbd button with dark bold Chinese label "登录并继续" and small right arrow. Its visual shows the enabled primary-action appearance in this design preview.

Under the button, centered readable 13px helper copy with a tiny lock icon: "请使用管理员分配的账号登录". Finally, a subdued 12px line "关闭窗口可继续浏览" with sufficient contrast, aligned centrally near the lower part of the form. Keep the form vertically balanced and neither cramped nor stretched.

No phone-number inputs, verification-code controls, agreement checkbox, forgot-password, registration, social icons or unsupported login options. Do not add an explicit guest-submit button: the X naturally returns to browsing. No visual annotation arrows, explanatory callouts or screenshot comparison panels.

### Delivery and future implementation boundary

The output is one screenshot of the modal OPEN over the guest creation page. It must convey that the underlying home exists independently from sign-in. The modal is the first focal point, with rich artwork and restrained readable form balanced inside it. Accurate text and alignment matter.

In a future implementation, modal composition would use the existing Ant Design Modal, Form, Input and Input.Password, connected to the same auth API. All text and controls are editable DOM; the film still is an independent asset. This image is design-only, not proof that guest routes, public examples, permission gates or return-after-login currently work. No mobile view is requested. Do not display these implementation notes in the generated image.


## 2026-10-31 实现状态

本设计已落地，当前行为、兼容性、验证与回滚以 `../../ARCHITECTURE.md` 中「2026-10-31 游客生成首页与按需登录弹窗」为准。前文生成提示词保留为历史设计输入；真实页面使用既有创作表单和独立媒体素材。

### 实际页面基线

桌面逻辑视口 1920×1080；弹窗约 816×550px（含边框），媒体/表单约 48:52。已按生成稿的 1536→1920 映射核对关键区域，真实页面复用现有首页；主视觉单独重建，无整张截图伪装页面。

- [暗色实际页面](implementation-20261031/login-dark.webp)
- [浅色实际页面](implementation-20261031/login-light.webp)
- 实际几何、请求路径和验收结果见 `implementation-20261031/verification.json`。

原始 v002 API 提示词已按原 SHA-256 精确归档至 `prompts/modal-v002.md`，避免后续实现记录混入生成输入。测试截图先输出到已忽略的 `test-results/auth/`，正式基线留在本目录，临时日志和排查文件在验收后清理。


### 2026-10-31 输入框阴影与浏览器补全修正

移除账号自动聚焦以及输入框焦点外发光，仅保留聚焦边框；表单/账号设置关闭补全，密码使用 `new-password` 提示以抑制已有密码自动填入。浏览器仍触发自动填充时，填充层的底色与文字按当前主题覆盖，避免蓝灰色内块。使用标准 Ant Design 输入组件，不修改浏览器设置、已保存账号或登录接口。

5173 内置浏览器与 Chrome 桌面检查：新开弹窗两字段为空且不聚焦输入框，浅暗两主题外层 `box-shadow` 均为 `none`；类型检查通过。修正后的[暗色输入框](implementation-20261031/inputs-dark.webp)与[浅色输入框](implementation-20261031/inputs-light.webp)作为补充基线。

浏览器密码管理器可能覆盖网页 autocomplete 提示，网页不保证屏蔽浏览器主动展示或用户手动打开的密码建议，参考 [MDN](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Turning_off_form_autocompletion)。

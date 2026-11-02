# ZLY AI Studio 登录页设计 v001

日期：2026-10-31。范围：一张桌面端登录页设计图，暂不实现代码。

## 目标和参考

将现有空旷的深色分栏登录页改为有作品氛围、清晰登录焦点的创作平台入口。

参考站点：
- https://jimeng.jianying.com/ ：当前浏览器已登录，观察的是创作首页的作品表达，未退出用户账号。
- https://app.runwayml.com/login ：实际查看了左侧作品区域、右侧白色登录表单。
- 用户提供的现有页面截图：用于确认品牌和现有账号密码登录方式。

以上均为观察后的文字提炼参考；本次生成不上传参考截图，不作像素复刻。

当前业务只支持管理员分配的账号密码登录，不设计自助注册、第三方登录、短信验证或不存在的找回密码功能。现有代码入口为 frontend/src/auth/AuthScreens.tsx；作品权限、云存储和运行服务均不属于登录页主信息。

## 图像生成任务

Generate ONE extremely polished, realistic desktop web UI design for the actual Chinese AI filmmaking product "ZLY AI Studio". This is a production-style LOGIN SCREEN, displayed straight on, edge to edge, no browser chrome, no device, no perspective, no design-board labels or measurements. Output a single 16:9 image at 1536×864 pixels, representing a desktop logical viewport 1920×1080. All text must be beautifully rendered, sharp, readable, accurate simplified Chinese. The overall impression is a thoughtful creative product with an exceptional cinematic artwork, balanced by a restrained clear form.

### Composition

The left 63% is an immersive cinematic artwork stage. The right 37% is a quiet very light login area with background #f8f9fa. No empty black column. The left side is intentionally visually rich; the right side has generous but purposeful spacing and a perfectly aligned form. The join is clean and architectural, without a heavy divider or border.

### Left visual stage

Fill the left stage with an exceptional ORIGINAL cinematic image: a young adult East Asian woman in a flowing muted burnt-orange coat stands in a vast black volcanic landscape with thin reflective water, wind moving her coat, looking toward a monumental circular amber sun low on the horizon. Dark slate and deep jade atmospheric mountains, soft mist, compelling realistic cinema lighting, sophisticated photographic composition, subtle natural texture. The human figure is relatively small, positioned near the middle-right of the artwork stage, so the landscape has scale. The amber sun and orange coat provide a beautiful warm focal point against deep charcoal and cool slate. It is a still from an imaginary art film, not a generic neon AI wallpaper. Avoid illustration, generic abstract gradients, spheres, wireframes, tech HUDs and rainbow glows.

At the top-left, place the product's restrained brand: a small mint-turquoise four-point sparkle line icon with text "ZLY AI Studio" in a modern medium-weight sans serif, approximately 22px at logical viewport. The mark is the existing sparkle idea refined, not an entirely new elaborate logo. Keep approximately 64px logical padding from the left and top.

Use a smooth deep charcoal scrim over the lower portion of the artwork so white type has excellent contrast. In the lower left, set a small spaced caption "你的 AI 影像创作空间", followed by the large bold Chinese headline on TWO deliberate lines:
"让灵感，"
"成为下一幕。"
The headline is approximately 60px logical size, confident contemporary Chinese sans serif, not calligraphy, not excessively heavy. Beneath it, add one crisp understated sentence: "从一张图，到一个完整的故事。" in soft off-white at 18px logical size.

Near the lower-right of the artwork stage, show a subtle horizontal filmstrip of THREE small cinematic thumbnails with 12px corners and consistent spacing, each about 132×88px logical size. First thumbnail: a closer crop from the main orange-coat film, with a thin mint selection border. Second: an elegant period-drama woman in an ivory costume under Chinese architectural eaves with warm lanterns, film still. Third: an appealing stylized 3D animated white cat astronaut on a dusty peach miniature planet. The filmstrip is small, tasteful, grounded in the artwork, not a scattered collage or dashboard cards. Do not add labels, fake playback buttons or fake product statistics. Place three tiny pagination indicators underneath the filmstrip, first indicator an elongated mint pill.

### Right login area

The right panel is #f8f9fa with deep ink text #171a1f. It must feel clean and calm, with clear typographic hierarchy and no giant decorative shield icon, no outer card border, no glass effects.

At the top-right, put a small 40px circular outline icon button showing a simple sun/moon theme icon in neutral grey, aligned at 40px logical inset. This is the existing root theme switch concept.

Center an approximately 400px-wide form horizontally in the right panel, positioned slightly above the vertical middle. Maintain deliberate rhythm. Top small uppercase eyebrow "WELCOME BACK" in neutral grey, 12px letter-spaced; below it an elegant bold 32px Chinese title "登录，开始创作"; below that a 15px secondary line "欢迎回到 ZLY AI Studio".

After a 36px gap, use a crisp left-aligned label "账号" at 14px, then a 52px-high rounded-12 input, white background, fine grey #dfe3e8 border, subtle user outline icon at left, placeholder "请输入你的账号" in readable muted grey. No autofilled real username.

After a 24px gap, label "密码" and a matching 52px-high input, a tiny lock outline icon at left, placeholder "请输入密码", and a small eye outline icon at the far right. Make the two fields exactly equal width and height with excellent baseline alignment. Ant Design compatible component proportions, no unusually styled custom controls.

After a 28px gap, show ONE wide 52px-high vivid mint-turquoise #13dfbd primary button, 12px corners, dark ink bold text "登录工作台", and a small right arrow. This is the visual action focus. The button is a design preview of its enabled appearance; no need to illustrate disabled validation states on the same screen.

Below the button after 24px, add a small neutral-grey lock outline icon and the sentence "请使用管理员分配的账号登录" at 13px, centered and plainly legible. No registration link, no forgot-password link, no WeChat, Google, Apple or other social login, no QR code, no terms-consent checkbox, no remember-me control, no unsupported functionality.

At the very bottom of the right panel, place a small quiet footer "ZLY AI Studio · 让创作发生" centered with approximately 36px bottom inset. No copyright year or fake certification.

### Rules and implementation boundary

This is the light-theme design direction: dark artwork is media content, the form uses the project's light surface and text baseline. Future dark-theme implementation will use the same composition and the existing root theme state with #0f1115 canvas, #171a20 surface, #f3f5f7 text and readable neutral borders, not a separate theme state. Only the light preview is requested in this image.

Use Noto Sans SC / PingFang SC / Microsoft YaHei type proportions with a modern neutral Latin sans serif. Work on an 8px spacing rhythm. Ensure labels, helper copy and placeholders are legible at normal desktop scale. The image stage, title and single action form a clear hierarchy.

In later implementation, the artwork is an independent image asset; all text, icons, fields, theme control and button remain editable DOM elements; forms will directly use Ant Design components and theme tokens. Do not depict implementation notes in the image. No mobile adaptation or mobile mockup is in scope.

The generated result must look like a finished premium web product screenshot, not a poster, mood board, annotated specification, template gallery, sales landing page or wireframe.

# V3 实际生成提示词

## 首次生成

输入顺序：1. 现有 ZLY 设计图；2. 即梦公开首页截图；3. Krea App 截图；4. Higgsfield 首页截图。对应图片已实际传入 ImageGen。

Use case: ui-mockup.
Design a new V3 homepage for the existing Chinese AI image/video application ZLY AI Studio. ONE complete polished desktop interface, front-facing flat screen, approximately 1600x1000, high-resolution Chinese text. This is an actual production tool, not a marketing landing page. The user rejected an earlier giant editorial hero and then rejected a perfectly regular 4-by-2 gallery as boring. The new design must remain COMPACT while having a clear creative point of view and an engaging rhythm.

ACTUAL IMAGE REFERENCES AND THEIR ROLES:
Image 1: ZLY's existing screen. Preserve only its product identity, existing sparkle mark, navigation labels, paired floating header groups and task history structure. Recompose the main area freely.
Image 2: the actual public Jimeng/即梦 homepage captured today. Borrow its creation-first hierarchy: small central greeting, a focused prompt surface, then compact media-assisted shortcuts. Ignore its advertising banner, login rewards popover, product branding, pricing, extra tools, and dark color scheme.
Image 3: the actual Krea app home captured today. Borrow the feeling that work imagery surrounds a focused creation instrument, with lightweight chrome and varied image framing. Ignore its blur, black theme, account offers and its models.
Image 4: the actual Higgsfield homepage captured today. Borrow the difference in visual weight between media-led entry points and small secondary affordances. Ignore its bright lime branding, advertisements, English copy and any features not in ZLY.
These are inspiration for design relationships, not UI copies to stitch together.

DESIGN IDEA: a compact creative studio with a beautiful prompt instrument at the top, a small cinematic doorway into the existing tools, and a living contact sheet of recent work below. Quiet app typography and precise controls; expressiveness comes from the composition and a curated variety of imagery. There must be a strong reading path: type an idea -> choose a route if needed -> continue a recent work. This must feel materially different from a normal dashboard card grid.

LIGHT THEME THROUGHOUT. Canvas #f8f9fa, white surfaces, dark ink #171a1f, slate secondary text, subtle grey keylines. Indigo #435ce8 only for main action, selected navigation and meaningful active states. No gradient headline, purple haze, neon, fake KPI charts, ornamental particles, oversized slogans, or glass blur. Refined Chinese sans-serif like PingFang SC. Normal interface text 12–14px, section labels 14px, central greeting ONLY 25–27px in ONE line. Control heights about32px, icon size14–18px. Nothing inflated.

KEEP THE SHELL SMALL:
Top floating left group at x16,y12,height44: outlined sparkle logo, "ZLY AI Studio" and smaller "创作工作台". Top floating right group: green semantic state dot plus "ComfyUI · 已连接", moon icon, small avatar 高, account 高睿海, chevron. Middle top has open canvas.
Left 72px icon rail below y72, nav 生成 selected / 导演台 / 画布 / 资产, small line icons and11px labels.
Next approximately228px task sidebar, white, thin divider. "开启创作"14px, sub "44 个视频任务", small collapse icon, "全部用户" compact Select, small "+ 新对话", search field. Grouped 今天 / 昨天 / 过去7天 / 更早. Tight36px history rows,24px thumbnails,13px single-line titles such as 雨夜街头 / 山谷云海 / 午后人像 / 海岸日落 / 沙漠旅人 / 森林小屋. Pair status color with tiny check or queue icons. Do not give every row a large second line. Bottom "查看全部任务 44". The main content begins around x330.

TOP CREATION AREA, DIRECT AND COMPACT:
Within the main area, at y104, centered small greeting "今天，想拍点什么？". No large supporting paragraph or hero image.
Below at approximately x416,y153,width1060,height180: a single crisp white prompt instrument with16px corners, a fine border and restrained soft shadow. This is the first visual and functional focus. It MUST be noticeably slimmer than the reference's giant bottom panel. Main input is an open UNBOXED area, not a giant nested bordered textarea.
Two tiny first/last-frame attachment slots, approx52x64px, at left: image-plus outline and "首帧", "尾帧（可选）". To their right14px placeholder "描述一个画面，或上传参考图开始创作…" with ample room for two lines. Small quiet upload hint optional.
A tiny utility row in the upper-right contains "提示词优化" with a small ON switch, dropdown "电影级通用叙事", text action "立即润色".
Bottom within the SAME panel one32px toolbar: Select "视频生成", fully visible model "MiniMax H3 首尾帧视频", aspect "16:9", duration "5 秒", "更多设置", and one solid indigo "开始生成" at far right,112x34px. Muted "Ctrl + Enter" can sit nearby without adding a tall footer. No internal sampler, node or GPU-memory settings. All components look like refined Ant Design controls.
No separate big labels such as "创作描述" taking up another row.

SMALL MEDIA-LED TOOL DOORWAYS BELOW THE PROMPT:
Between y370 and approximately y490, a restrained asymmetrical shortcut composition into REAL existing product capabilities. One wider low cinematic entry for "导演台" with supporting line "从剧本到镜头，连成一个故事" and an arrow; pair a tight image crop on one side with clear text, not a giant banner. Alongside, two lighter, compact image-and-text entries for "图片生成" / "把想法变成参考画面" and "无限画布" / "把素材放在一起，自由编排". Give these subordinate entries a different horizontal proportion or stack them; do not make three identical dashboard tiles. Use actual cinematic material in the thumbnails: a moody film scene, a clean object photograph, a miniature image-composition board respectively. These are short product entry links, no new features, no claims about models or speed. They should feel like a small creative tool belt, not marketing feature cards. No extra unrelated slogans.

LOWER WORK AREA, A LIVING CONTACT SHEET:
Start near y545 with "最近创作"14px and quiet text filters 全部 / 视频 / 图片. Small "查看全部" at the opposite end.
Below, MIXED-ASPECT image previews in a deliberately art-directed but practical layout, with a few different widths and natural aspect ratios. Create a real rhythm: one moderately wider landscape frame, a narrow vertical frame, and a pair of smaller frames. The bottoms DO NOT all align and there is NOT a 4x2 matrix of identical cards. A scroll continuation may be suggested naturally by the next thumbnails near the bottom edge, but do not cut off captions or action controls. Make media the focus; no white card footer boxes or heavy borders. Titles are tiny13px below each image, with a short muted time and small duration inside video thumbnails. No giant gallery heading.
Use a more distinctive MIX of real creative outputs than the previous mountains-only scenic selection:
- an adult in a vivid red coat on a wet silver coast, cinematic wide frame, a meaningful focal shot;
- a tall portrait of an adult fashion model in a dark tailored outfit near a sculptural chrome chair, editorial light;
- an amber glass perfume bottle in hard sunlight, clean creative product still;
- a painterly animated city train arriving at dusk, original non-franchise animation style;
- a surreal pale-blue ocean with a floating architectural arch, imaginative film concept.
Keep a controlled photographic/art palette of red, warm amber, ocean blue and neutral silver rather than random neon. The imagery is illustrative mock content. Sample titles: "海边追光", "光影人像", "午后光线", "末班列车", "另一片海". Show a believable selection, not dozens of tiny thumbnails. Compact controls, clear affordances and precise aligned text remain disciplined even where the media rhythm is asymmetric.

NONNEGOTIABLES: respect the compact scale the user requested. No giant first-screen photo hero and no oversized two-line headline. No regular equal-size dashboard grid. Existing ZLY branding and light theme are preserved; do not import competitor branding, lime, black theme, login overlays or sale banners. No invented tools like smart erase, camera hardware setup or community marketplace. Elegant, mature and visually specific; the page should look like a creative environment someone wants to work in every day, not a gallery template. All text and actions legible. Full viewport design only, no outer annotations, no watermark.

## 定向修正

输入：本轮首次生成的设计图。保留画面与构图，仅收紧密度、修正上传能力文案及任务状态图标。

Edit this ZLY AI Studio V3 design as a FINAL COMPACTNESS AND COPY CORRECTION pass. Preserve the exact light theme, logo, all navigation, floating top groups, task sidebar, all five gallery artworks, their asymmetric mixed-aspect composition, and the three tool entry meanings. Keep the first-image larger coastal red-coat artwork and the stacked photo/train arrangement; these are the successful new visual direction.

Make the central functional UI visibly tighter without shrinking the entire screenshot:
1. The one-line greeting "今天，想拍点什么？" should be only about25px, normal semibold, not36–40px. Keep it centered in the available main area, no subtitle.
2. Reduce the prompt panel from its current approximately230px height to about180–190px. Keep its width about1060–1120px centered in the MAIN column. Use14px interior padding,14px corners. First/last-frame upload tiles shrink to approx56×68px. Open typing area is compact with no separate nested border. Selects/buttons along the bottom are32–34px high with12–13px labels, and the main generate button about112×34px. The long model label must remain fully readable: "MiniMax H3 首尾帧视频". Do not remove the first or optional last frame or the prompt optimization switch.
3. CRITICAL PRODUCT COPY FIX: this selected workflow accepts reference IMAGES, not input video. Replace the incorrect hint "支持图片、视频，拖拽上传或点击添加" with exactly "支持粘贴图片，或拖入参考图". Do not show any video-upload capability.
4. Reduce the tool doorway strip from approximately190px high to approximately130px, with the large director tile at left and the two slim entries stacked at right still having DIFFERENT visual weights. Tool headings only18–20px, descriptions12px. Keep legibility of all overlaid text: put director text on the calm pale sky portion of its photograph, not against the red coat or busy waves. The three true entries remain 导演台 / 图片生成 / 无限画布.
5. Pull the recent-work header and mixed-aspect previews upward with the space saved so the full preview titles and time labels remain comfortably visible, with a small breathing margin at the bottom. Do not convert the gallery to an equal-sized grid. The vertical fashion portrait, wider coastal still, two smaller stacked images and narrow surreal seascape retain their distinct proportions.
6. Improve task status semantics very subtly: completed tasks use a tiny check-in-circle, waiting tasks a clock, with the existing colors. No color-only states. Preserve the tight task list and bottom count44.

Everything should now feel like a high-quality compact production application, with a25px headline,13px normal text and34px controls. No new elements, no giant banners, no advertising, no new branding, no dark-theme switch within the image, no new photos. Preserve the artwork and composition; change the density and the one misleading upload hint. One full front-facing desktop screen at the same aspect ratio as the reference, crisp Chinese text, no watermark.

import { Button } from "antd"
import { ArrowUpRight } from "lucide-react"

const examples = [
  { title: "日落之后", image: "/auth/cinematic-shore.webp", prompt: "落日映照着山海，一位穿橙色风衣的女人站在礁石岸边，海风吹起衣角，镜头缓慢向前推进。" },
  { title: "光影人像", image: "/auth/sample-portrait.webp", prompt: "午后的柔光落在人物脸上，人物自然地望向窗外，镜头缓慢靠近，画面安静而真实。" },
  { title: "午后光线", image: "/auth/sample-perfume.webp", prompt: "琥珀色香水瓶放在石材桌面上，阳光穿过树叶，光影轻轻晃动，微距特写。" },
  { title: "末班列车", image: "/auth/sample-train.webp", prompt: "暮色中的小镇车站，一列暖黄色灯光的列车缓缓驶来，天空是柔和的紫色，动画电影质感。" },
  { title: "另一片海", image: "/auth/sample-sea.webp", prompt: "蔚蓝海面上矗立着一座白色拱门，白云缓缓飘过，远处的人物走向光线，超现实电影画面。" },
]

export default function GuestInspiration({ onUse }: { onUse: (prompt: string) => void }) {
  return <section className="studio-guest-inspiration" aria-labelledby="studio-guest-inspiration-title">
    <div className="studio-home-recent-header"><h2 id="studio-guest-inspiration-title">灵感示例</h2><span>从一个画面开始</span></div>
    <div className="studio-guest-gallery">
      {examples.map((example) => <Button key={example.title} type="text" onClick={() => onUse(example.prompt)} className="studio-guest-example" aria-label={`使用灵感：${example.title}`}>
        <img src={example.image} alt="" loading="lazy" />
        <span className="studio-guest-example-title">{example.title}<ArrowUpRight size={15} /></span>
      </Button>)}
    </div>
  </section>
}

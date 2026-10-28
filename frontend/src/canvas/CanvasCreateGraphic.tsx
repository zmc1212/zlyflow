import { FileText, Image as ImageIcon, Play, Plus, Type } from "lucide-react"

/** Decorative geometry for the create action, independent of project data. */
export default function CanvasCreateGraphic() {
  return (
    <svg className="canvas-home-create-graphic" viewBox="0 0 400 190" aria-hidden="true" focusable="false">
      <path className="canvas-home-create-brackets" d="M20 34V18h16 M364 18h16v16 M380 156v16h-16 M36 172H20v-16" />
      <g className="canvas-home-create-lines">
        <path d="M126 51C173 51 151 95 200 95M274 51C227 51 249 95 200 95M126 144C173 144 151 95 200 95M274 144C227 144 249 95 200 95" />
      </g>
      {[
        { x: 110, y: 35, Icon: ImageIcon },
        { x: 258, y: 35, Icon: Type },
        { x: 110, y: 128, Icon: Play },
        { x: 258, y: 128, Icon: FileText },
      ].map(({ x, y, Icon }) => (
        <g key={`${x}-${y}`}>
          <rect className="canvas-home-create-node" x={x} y={y} width={32} height={32} rx={7} />
          <Icon x={x + 8} y={y + 8} width={16} height={16} strokeWidth={1.5} />
        </g>
      ))}
      <rect className="canvas-home-create-plus" x={179} y={74} width={42} height={42} rx={10} />
      <Plus className="canvas-home-create-plus-icon" x={189} y={84} width={22} height={22} strokeWidth={1.5} />
    </svg>
  )
}

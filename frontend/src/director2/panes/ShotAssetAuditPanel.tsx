import { Alert, Checkbox, Collapse, Input, Select, Space, Table, Button } from "antd"
import type { AssetAudit, AssetReference, ManifestEntry } from "../asset-manifest-api"

export default function ShotAssetAuditPanel({ audit, entries, beats, confirmations, edits, onConfirm, onEdit }: {
  beats: {id: string; sequence?: number}[];
  audit: AssetAudit; entries: ManifestEntry[]; confirmations: Record<string, boolean>;
  edits: Record<string, AssetReference[]>; onConfirm: (id: string, value: boolean) => void;
  onEdit: (id: string, refs: AssetReference[]) => void;
}) {
  return <Collapse style={{marginTop: 16}} defaultActiveKey={audit.status === "pending" ? ["audit"] : []} items={[{key: "audit", label: `逐镜资产核对 · ${audit.status === "pending" ? "有歧义待确认" : "已核对，采纳前可修订"}`, children: <Space orientation="vertical" style={{width: "100%"}}>
    <Alert type="info" title="只有可见人物进入图片参考；画外和提及保留证据。修订关联不会改写镜头。" />
    {audit.shots.map((shot, i) => {
      const refs = edits[shot.id] || shot.references
      return <Collapse key={shot.id} items={[{key: shot.id, label: `镜头 ${beats.find(b => b.id === shot.id)?.sequence ?? i + 1} · ${refs.map(r => `${entries.find(e => e.id === r.manifest_id)?.name || r.name}（${({visible: "可见", offscreen: "画外", mentioned: "提及"} as Record<string,string>)[r.appearance]}）`).join("、") || "无关联"}`, children: <>
        {shot.issues.length > 0 && <Alert type="warning" title={shot.issues.join("；")} />}
        <Table rowKey="key" pagination={false} size="small" dataSource={refs.map((ref, index) => ({...ref, key: `${shot.id}:${index}`}))} columns={[
          {title: "资产／造型", render: (_, r, index) => <Select style={{minWidth: 160}} value={r.manifest_id} options={entries.map(e => ({value: e.id, label: `${e.name} · ${e.era || "未明确"}`}))} onChange={manifest_id => onEdit(shot.id, refs.map((v,n) => n === index ? {...v, manifest_id} : v))} />},
          {title: "出现方式", render: (_, r, index) => <Select value={r.appearance} options={[{value: "visible", label: "可见"}, {value: "offscreen", label: "画外发声"}, {value: "mentioned", label: "仅提及"}]} onChange={appearance => onEdit(shot.id, refs.map((v,n) => n === index ? {...v, appearance} : v))} />},
          {title: "原文／本镜证据", render: (_, r, index) => <Input.TextArea rows={2} value={r.evidence} onChange={e => onEdit(shot.id, refs.map((v,n) => n === index ? {...v, evidence: e.target.value} : v))} />},
          {title: "操作", render: (_, _r, index) => <Button onClick={() => onEdit(shot.id, refs.filter((_, n) => n !== index))}>移除</Button>},
        ]} />
        <Space><Button disabled={!entries.length} onClick={() => onEdit(shot.id, [...refs, {manifest_id: entries[0].id, appearance: "visible", location: "action", evidence: ""}])}>补充关联</Button>
          <Checkbox checked={Boolean(confirmations[shot.id])} onChange={e => onConfirm(shot.id, e.target.checked)}>已核对本镜人物、造型、场景和道具</Checkbox></Space>
      </>}]} />
    })}
  </Space>}]} />
}

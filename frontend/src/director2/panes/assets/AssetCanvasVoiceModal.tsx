import { useQuery } from "@tanstack/react-query"
import { Button, Collapse, Form, Modal, Select, Slider, Space, Upload, message } from "antd"
import { listVoiceBank, type Director2Asset } from "../../api"
import { groupedVoicePresetOptions } from "../../voice-bank"
import { searchFilterOption } from "../../../search-match"
import { INDEXTTS_EMOTIONS, MAX_VOICE_AUDIO_BYTES, VOICE_AUDIO_ACCEPT, hasRefAudio, isVoiceAudioFile, voiceOf } from "../../voice-profile"

export default function AssetCanvasVoiceModal({ open, asset, onClose, uploading, previewing, applying, onUpload, onPreset, onPreview, onExtract, onExtraChange }: {
  open: boolean; asset: Director2Asset | null; onClose: () => void; uploading: boolean; previewing: boolean; applying: boolean
  onUpload: (file: File) => void; onPreset: (id: string) => void; onPreview: () => void; onExtract: () => void; onExtraChange: (patch: Record<string, unknown>) => void
}) {
  const bank = useQuery({ queryKey: ["director-voice-bank"], queryFn: listVoiceBank, enabled: open, staleTime: 60_000 })
  const voice = voiceOf(asset?.extra), bound = hasRefAudio(asset?.extra)
  return <Modal title={`${asset?.name || "角色"} · 形象音色`} open={open} onCancel={onClose} footer={<Button onClick={onClose}>完成</Button>} width={600} destroyOnHidden>
    <Form layout="vertical"><Form.Item label="选择角色声线"><Select aria-label="角色声线" placeholder="选择已有声线，或上传参考音" value={voice.preset_id || undefined} loading={bank.isLoading || applying} options={groupedVoicePresetOptions(bank.data?.voices || [])} showSearch filterOption={searchFilterOption} onChange={value => onPreset(value)}/></Form.Item></Form>
    <Space wrap><Upload accept={VOICE_AUDIO_ACCEPT} showUploadList={false} beforeUpload={file => { if (!isVoiceAudioFile(file) || file.size > MAX_VOICE_AUDIO_BYTES) { message.warning("请上传不超过 20 MB 的音频"); return Upload.LIST_IGNORE } onUpload(file); return false }}><Button loading={uploading}>{bound ? "更换参考音" : "上传参考音"}</Button></Upload><Button onClick={onExtract}>从成片提取</Button><Button disabled={!bound} loading={previewing} onClick={onPreview}>试听声线</Button></Space>
    {(voice.preview_url || voice.ref_audio_url) && <audio style={{ width: "100%", marginTop: 18 }} src={voice.preview_url || voice.ref_audio_url} controls preload="metadata"/>}
    <Collapse ghost style={{ marginTop: 16 }} items={[{ key: "performance", label: "更多声音设置", children: <Form layout="vertical"><Form.Item label="默认情绪"><Select value={voice.default_emotion} options={INDEXTTS_EMOTIONS.map(item => ({ value: item.id, label: item.label }))} onChange={value => onExtraChange({ voice: { ...voice, default_emotion: value } })}/></Form.Item><Form.Item label="情绪强度"><Slider min={0} max={1} step={.05} value={voice.emo_alpha} onChange={value => onExtraChange({ voice: { ...voice, emo_alpha: value } })}/></Form.Item></Form> } ]}/>
  </Modal>
}

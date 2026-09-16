import { Button, Input } from "antd"
import { ArrowRight, Pencil } from "lucide-react"
import {
  SCRIPT_DOCUMENT_EDIT_DONE_LABEL, SCRIPT_DOCUMENT_EDIT_LABEL, SCRIPT_DOCUMENT_NEXT_LABEL, SCRIPT_DOCUMENT_STORY_HINT,
} from "../action-copy"
import DirectorScriptCoverPicker from "./DirectorScriptCoverPicker"
import { ScriptLiveBlocks } from "../../director2/Director2ScriptLiveBody"

export type ScriptDocumentValue = { title: string; summary: string; fullStory: string; coverUrl?: string | null }

type Props = {
  script: ScriptDocumentValue
  mode: "document" | "edit"
  busy?: boolean
  onEdit: () => void
  onDoneEdit: () => void
  onChange: (patch: Partial<ScriptDocumentValue>) => void
  onNext: () => void
  onUploadCover?: (file: File) => void | Promise<void>
  onRemoveCover?: () => void | Promise<void>
}

function DocumentStory({ text }: { text: string }) {
  return <ScriptLiveBlocks text={text} />
}

/**
 * Finished-script view: a read-only manuscript by default, with an explicit
 * edit mode (the previous always-on form) kept behind an 编辑 action.
 */
export default function DirectorScriptDocument({
  script, mode, busy = false, onEdit, onDoneEdit, onChange, onNext, onUploadCover, onRemoveCover,
}: Props) {
  if (mode === "edit") {
    return (
      <div className="director-script-document is-editing">
        <div className="director-document-toolbar">
          <span className="director-document-hint">{SCRIPT_DOCUMENT_STORY_HINT}</span>
          <Button onClick={onDoneEdit} disabled={busy}>{SCRIPT_DOCUMENT_EDIT_DONE_LABEL}</Button>
        </div>
        {onUploadCover ? (
          <DirectorScriptCoverPicker
            coverUrl={script.coverUrl}
            busy={busy}
            compact
            onUpload={onUploadCover}
            onRemove={onRemoveCover}
          />
        ) : null}
        <div className="director-script-sheet">
          <label className="director-script-field">
            <span>片名</span>
            <Input
              value={script.title}
              readOnly={busy}
              placeholder="未命名故事"
              onChange={(event) => onChange({ title: event.target.value })}
            />
          </label>
          <label className="director-script-field">
            <span>一句话梗概</span>
            <Input.TextArea
              value={script.summary}
              readOnly={busy}
              placeholder="用一句话说清主角、目标与冲突"
              autoSize={{ minRows: 2, maxRows: 4 }}
              onChange={(event) => onChange({ summary: event.target.value })}
            />
          </label>
          <label className="director-script-field is-story">
            <span>完整故事 <em>{script.fullStory.trim().length} 字</em></span>
            <Input.TextArea
              value={script.fullStory}
              readOnly={busy}
              placeholder="完整写下故事进展、关键动作、对白与结尾。分镜会严格从这里拆解。"
              autoSize={{ minRows: 12, maxRows: 22 }}
              onChange={(event) => onChange({ fullStory: event.target.value })}
            />
          </label>
        </div>
      </div>
    )
  }

  return (
    <div className="director-script-document">
      <div className="director-document-toolbar">
        <Button icon={<Pencil size={14} />} onClick={onEdit} disabled={busy}>{SCRIPT_DOCUMENT_EDIT_LABEL}</Button>
        <Button type="primary" onClick={onNext} disabled={busy}>
          {SCRIPT_DOCUMENT_NEXT_LABEL}
          <ArrowRight size={14} />
        </Button>
      </div>
      {onUploadCover ? (
        <DirectorScriptCoverPicker
          coverUrl={script.coverUrl}
          busy={busy}
          compact
          onUpload={onUploadCover}
          onRemove={onRemoveCover}
        />
      ) : null}
      <article className="director-document-body">
        <h2 className="director-document-title">{script.title || "未命名故事"}</h2>
        {script.summary ? <p className="director-document-lead">{script.summary}</p> : null}
        <div className="director-document-story">
          <DocumentStory text={script.fullStory} />
        </div>
        <div className="director-document-meta">完整故事 · {script.fullStory.trim().length} 字</div>
      </article>
    </div>
  )
}

import { useQueryClient } from "@tanstack/react-query"
import { Button, Input, Modal, Select, message } from "antd"
import type { TextAreaRef } from "antd/es/input/TextArea"
import { ArrowUpRight, AudioLines, ChevronDown, Clock3, SlidersHorizontal } from "lucide-react"
import { useRef, useState } from "react"
import { MusicChatDetail, MusicJob, createMusicChat, streamMusicChatMessage } from "./api"
import MusicCreateForm from "./MusicCreateForm"

const DURATION_OPTIONS = [{ label: "30秒", value: 30 }, { label: "1分钟", value: 60 }, { label: "3分钟", value: 180 }, { label: "3.5分钟", value: 210 }]

/**
 * 音乐对话 composer：home 态内联（studio-composer-inline），选中对话后底部停靠。
 * 发送语义：无对话先建对话再发首条消息；发送前乐观插入用户气泡，等待助手回复时禁用。「更多设置」直出高级表单。
 */
export default function MusicComposer({ csrfToken, chatId, draft, onDraftChange, disabled, configured, anchorJob, inline, onSendingChange, onStreamingReply, onOpenChat }: {
  csrfToken: string
  chatId: string | null
  draft: string
  onDraftChange: (value: string) => void
  disabled: boolean
  configured: boolean
  anchorJob: MusicJob | null
  inline: boolean
  onSendingChange: (sending: boolean) => void
  onStreamingReply: (text: string | null) => void
  onOpenChat: (chatId: string) => void
}) {
  const queryClient = useQueryClient()
  const editorRef = useRef<TextAreaRef>(null)
  const [instrumental, setInstrumental] = useState(false)
  const [duration, setDuration] = useState(180)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const sending = disabled

  const submit = async () => {
    const content = draft.trim()
    if (!content || sending || !configured) return
    onSendingChange(true)
    try {
      let targetChatId = chatId
      if (!targetChatId) {
        const chat = await createMusicChat(csrfToken, null)
        targetChatId = chat.id
        await queryClient.invalidateQueries({ queryKey: ["music-chats"] })
      }
      // 乐观插入用户气泡（LLM 可能要等几十秒；详情接口在发送前已把用户消息落库）
      if (queryClient.getQueryData(["music-chat", targetChatId])) {
        queryClient.setQueryData<MusicChatDetail>(["music-chat", targetChatId], (old) => old ? {
          ...old,
          messages: [...old.messages, {
            id: `temp-${Date.now()}`, chat_id: targetChatId as string, role: "user" as const,
            content, proposal: null, job_id: null, created_at: null,
          }],
        } : old)
      }
      await streamMusicChatMessage(csrfToken, targetChatId, content, { duration_seconds: duration, instrumental }, {
        onDelta: (text) => onStreamingReply(text),
      })
      onDraftChange("")
      onStreamingReply(null)
      onOpenChat(targetChatId)
      void queryClient.invalidateQueries({ queryKey: ["music-chat", targetChatId] })
    } catch (error) {
      message.error(error instanceof Error ? error.message : "音乐助手暂时没有接上，请重试")
      void queryClient.invalidateQueries({ queryKey: ["music-chats"] })
      if (chatId) void queryClient.invalidateQueries({ queryKey: ["music-chat", chatId] })
    } finally {
      onSendingChange(false)
      onStreamingReply(null)
    }
  }

  return <>
    <form
      id="studio-music-composer"
      className={`studio-composer-form studio-music-composer relative z-20 mx-auto max-w-[1080px] border border-black/[0.05] bg-white p-4 shadow-[0_16px_36px_rgba(22,31,44,0.10)] sm:rounded-[24px] sm:p-5 lg:sticky lg:bottom-5 ${inline ? "studio-composer-inline" : ""}`}
      onSubmit={(event) => { event.preventDefault(); void submit() }}
    >
      <Input.TextArea
        ref={editorRef}
        className="studio-music-composer-editor"
        aria-label="音乐创作描述"
        placeholder={anchorJob ? `想怎么改《${anchorJob.title || "这首歌"}》？副歌、歌词、风格都可以` : "描述一种心情、一段故事，或你脑海里的旋律…"}
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        autoSize={{ minRows: 2, maxRows: 7 }}
        variant="borderless"
        maxLength={2000}
        disabled={sending || !configured}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() }
        }}
      />
      <div className="studio-music-composer-toolbar">
        <Select className="studio-music-voice" aria-label="歌曲类型" value={instrumental ? "instrumental" : "vocal"}
          onChange={(value) => setInstrumental(value === "instrumental")} disabled={sending || !configured}
          prefix={<AudioLines size={18} />} suffixIcon={<ChevronDown size={15} />}
          options={[{ value: "vocal", label: "人声歌曲" }, { value: "instrumental", label: "纯音乐" }]} />
        <Select className="studio-music-duration" aria-label="歌曲时长" value={duration}
          onChange={setDuration} disabled={sending || !configured}
          prefix={<Clock3 size={18} />} suffixIcon={<ChevronDown size={15} />}
          options={DURATION_OPTIONS.some((option) => option.value === duration) ? DURATION_OPTIONS : [...DURATION_OPTIONS, { label: `${duration}秒`, value: duration }]} />
        <Button className="studio-music-tool" icon={<SlidersHorizontal size={18} />} disabled={sending || !configured}
          onClick={() => setAdvancedOpen(true)}>更多设置</Button>
        <span className="studio-music-toolbar-spacer" />
        <span className="studio-music-keyboard-hint">{draft.length > 1800 ? `${draft.length}/2000` : "Enter 发送 · Shift+Enter 换行"}</span>
        <Button type="primary" className="studio-music-send" htmlType="submit" loading={sending}
          disabled={!configured || !draft.trim()}>发送 <ArrowUpRight size={18} /></Button>
      </div>
    </form>
    <Modal open={advancedOpen} onCancel={() => setAdvancedOpen(false)} footer={null} width={760}
      title="直接生成（跳过助手提案）" destroyOnHidden className="studio-music-advanced-modal">
      <p className="studio-music-advanced-note">手写风格与歌词直接入队生成；想用对话慢慢改，直接在上方输入框描述即可。</p>
      <MusicCreateForm csrfToken={csrfToken} disabled={!configured} onCreated={() => setAdvancedOpen(false)} />
    </Modal>
  </>
}

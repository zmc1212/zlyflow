import { Button, Tooltip, message } from "antd"
import { Copy } from "lucide-react"
import { useState } from "react"
import { jsonMutation, requestJson } from "../api"

export type SecretProvider = "llm" | "vlm" | "tts" | "grs" | "qiniu"
export type SecretField = "api_key" | "access_key" | "secret_key"

type Props = {
  /** 出现在提示与「XX已复制」里的字段名。 */
  label: string
  /** 输入框当前值：非空时直接复制它，不再请求后端。 */
  value?: string | null
  csrfToken: string
  /** 传入后，输入框为空时改为取回已保存的明文凭据。 */
  provider?: SecretProvider
  field?: SecretField
}

export function CopyFieldButton({ label, value, csrfToken, provider, field = "api_key" }: Props) {
  const [loading, setLoading] = useState(false)
  const typed = (value || "").trim()

  async function write(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      message.success(`${label}已复制`)
    } catch {
      message.error("浏览器拒绝了剪贴板访问，请手动选中复制")
    }
  }

  async function copy() {
    if (typed) {
      await write(typed)
      return
    }
    if (!provider) {
      message.info(`${label}还是空的，没有可复制的内容`)
      return
    }
    setLoading(true)
    try {
      const result = await requestJson<{ value: string | null }>(
        "/api/admin/providers/secret",
        jsonMutation(csrfToken, { provider, field }),
      )
      if (!result.value) message.info(`还没有已保存的${label}，或当前凭证主密钥无法解密`)
      else await write(result.value)
    } catch (error) {
      message.error(error instanceof Error ? error.message : `${label}复制失败`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Tooltip title={typed || !provider ? `复制${label}` : `复制已保存的${label}`}>
      <Button
        type="text"
        size="small"
        loading={loading}
        onClick={copy}
        icon={<Copy size={14} />}
        aria-label={`复制${label}`}
      />
    </Tooltip>
  )
}

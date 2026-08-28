import { Button, Modal } from "antd"
import { useState } from "react"
import { summarizeJobError } from "../director-submit"

export default function JobErrorNotice({
  error,
  hideSummary = false,
}: {
  error?: string | null
  hideSummary?: boolean
}) {
  const [open, setOpen] = useState(false)
  const { summary, detail } = summarizeJobError(error)
  if (!summary) return null
  const showDetail = detail.length > summary.length
  const showSummary = !hideSummary || !showDetail
  return (
    <div className="director-job-error">
      {showSummary ? <p className="director-job-error-summary">{summary}</p> : null}
      {showDetail ? (
        <>
          <Button type="link" size="small" danger className="director-job-error-detail-btn" onClick={() => setOpen(true)}>
            查看错误详情
          </Button>
          <Modal
            title="失败详情"
            open={open}
            onCancel={() => setOpen(false)}
            footer={<Button onClick={() => setOpen(false)}>关闭</Button>}
            width={720}
            destroyOnHidden
          >
            <pre className="director-job-error-pre">{detail}</pre>
          </Modal>
        </>
      ) : null}
    </div>
  )
}

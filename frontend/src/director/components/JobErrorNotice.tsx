import { Button, Modal } from "antd"
import { useState } from "react"
import { summarizeJobError } from "../director-submit"

export default function JobErrorNotice({ error }: { error?: string | null }) {
  const [open, setOpen] = useState(false)
  const { summary, detail } = summarizeJobError(error)
  if (!summary) return null
  const showDetail = detail.length > summary.length
  return (
    <div className="director-job-error">
      <p className="director-job-error-summary">{summary}</p>
      {showDetail ? (
        <>
          <Button type="link" size="small" className="director-job-error-detail-btn" onClick={() => setOpen(true)}>
            查看详情
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

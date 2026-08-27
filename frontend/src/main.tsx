import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ConfigProvider } from "antd"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import Root from "./Root"
import { studioTheme } from "./theme"
import "antd/dist/reset.css"
import "./index.css"

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ConfigProvider theme={studioTheme}>
        <QueryClientProvider client={queryClient}><Root /></QueryClientProvider>
      </ConfigProvider>
    </BrowserRouter>
  </StrictMode>,
)

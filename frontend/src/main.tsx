import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import Root from "./Root"
import { StudioThemeProvider } from "./ThemeProvider"
import "antd/dist/reset.css"
import "./index.css"

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <StudioThemeProvider>
        <QueryClientProvider client={queryClient}><Root /></QueryClientProvider>
      </StudioThemeProvider>
    </BrowserRouter>
  </StrictMode>,
)

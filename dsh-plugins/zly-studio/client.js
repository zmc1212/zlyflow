window.__ModuleLoader__.load({
  id: 'zly-studio-dsh-plugin',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useCallback, useEffect, useLayoutEffect, useRef, useState } = React

    const NS = 'zly-studio'
    const PANEL_ID = 'zly-studio'
    const URL_KEY = 'zly-studio:base-url'
    const MODE_KEY = 'zly-studio:fit-mode'
    const DEFAULT_URL = 'https://comfyui.zlyun168.com'
    // The studio shell switches to its desktop layout at this viewport width
    // (Tailwind `xl`). Narrower frames get scaled instead of reflowed.
    const DESKTOP_WIDTH = 1280

    const zh = {
      'panel.label': 'ZLY 视频工作台',
      'panel.title': 'ZLY AI 视频工作台',
      'panel.subtitle': '创作 · 导演台 · 任务',
      'action.reload': '重新加载',
      'action.browser': '在浏览器打开',
      'action.settings': '服务地址',
      'action.save': '保存',
      'action.cancel': '取消',
      'action.fit': '适应面板',
      'action.actual': '原始比例',
      'mcp.connect': '连接 MCP',
      'mcp.connected': 'MCP 已连接',
      'mcp.waiting': '等待授权…',
      'settings.title': '工作台服务地址',
      'settings.hint': '默认连接公网部署；本地调试可改为 http://127.0.0.1:7865。',
      'mode.fitHint': '按桌面宽度渲染并等比缩放，避免工作台切到窄屏布局',
      'mode.actualHint': '按面板实际宽度渲染，使用工作台自身的响应式布局',
    }

    const en = {
      'panel.label': 'ZLY Video Studio',
      'panel.title': 'ZLY AI Video Studio',
      'panel.subtitle': 'Create · Director · Tasks',
      'action.reload': 'Reload',
      'action.browser': 'Open in browser',
      'action.settings': 'Studio URL',
      'action.save': 'Save',
      'action.cancel': 'Cancel',
      'action.fit': 'Fit panel',
      'action.actual': 'Actual size',
      'mcp.connect': 'Connect MCP',
      'mcp.connected': 'MCP connected',
      'mcp.waiting': 'Waiting…',
      'settings.title': 'Studio service URL',
      'settings.hint': 'Defaults to the public deployment; use http://127.0.0.1:7865 for local development.',
      'mode.fitHint': 'Render at desktop width and scale down, keeping the studio out of its narrow layout',
      'mode.actualHint': 'Render at the panel width and use the studio responsive layout',
    }

    let translate = (key) => key

    function normalizeUrl(input) {
      const raw = String(input || '').trim()
      if (!raw) return DEFAULT_URL
      try {
        const url = new URL(raw)
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return DEFAULT_URL
        return url.href.replace(/\/+$/, '')
      } catch {
        return DEFAULT_URL
      }
    }

    function readStored(key, fallback) {
      try {
        return localStorage.getItem(key) || fallback
      } catch {
        return fallback
      }
    }

    function storeValue(key, value) {
      try {
        localStorage.setItem(key, value)
      } catch {}
    }

    const styles = `
      .zly-studio-page{display:flex;flex-direction:column;flex:1;height:100%;min-height:320px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}
      .zly-studio-bar{flex:none;display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:40px;padding:6px 10px;box-sizing:border-box;border-bottom:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1);overflow:hidden}
      .zly-studio-brand{display:flex;align-items:baseline;gap:8px;min-width:0;overflow:hidden}
      .zly-studio-dot{width:8px;height:8px;border-radius:50%;background:var(--dsw-alias-state-success-primary);flex:none;align-self:center}
      .zly-studio-title{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .zly-studio-sub{font-size:11px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
      .zly-studio-actions{display:flex;align-items:center;gap:6px;min-width:0;flex:none}
      .zly-studio-url{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--dsw-alias-label-secondary);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
      .zly-studio-btn{appearance:none;box-sizing:border-box;height:26px;padding:0 9px;border-radius:6px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);font-size:11px;line-height:1;cursor:pointer;white-space:nowrap}
      .zly-studio-btn:hover{background:var(--dsw-alias-bg-overlay)}
      .zly-studio-btn:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px}
      .zly-studio-btn-primary{border-color:transparent;background:var(--dsw-alias-brand-primary);color:#ffffff}
      .zly-studio-btn-live{border-color:color-mix(in srgb, var(--dsw-alias-state-success-primary) 45%, transparent);color:var(--dsw-alias-state-success-primary)}
      .zly-studio-btn[aria-pressed="true"]{border-color:transparent;background:var(--dsw-alias-brand-primary);color:#ffffff}
      .zly-studio-form{display:flex;align-items:center;gap:6px;min-width:0;flex:1;justify-content:flex-end}
      .zly-studio-input{box-sizing:border-box;height:26px;min-width:180px;max-width:420px;flex:1;padding:0 9px;border-radius:6px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font-size:12px}
      .zly-studio-input:focus{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px;border-color:transparent}
      .zly-studio-stage{position:relative;flex:1;min-height:0;overflow:hidden;background:var(--dsw-alias-bg-base)}
      .zly-studio-frame{position:absolute;top:0;left:0;display:block;border:0;background:var(--dsw-alias-bg-base)}
    `

    function StudioPage() {
      const [base, setBase] = useState(() => normalizeUrl(readStored(URL_KEY, DEFAULT_URL)))
      const [draft, setDraft] = useState(base)
      const [nonce, setNonce] = useState(0)
      const [editing, setEditing] = useState(false)
      const [mode, setMode] = useState(() => (readStored(MODE_KEY, 'fit') === 'actual' ? 'actual' : 'fit'))
      const [box, setBox] = useState({ width: 0, height: 0 })
      const [mcp, setMcp] = useState({ connected: false, expiresAt: null, lastError: '' })
      const [mcpBusy, setMcpBusy] = useState(false)
      const stageRef = useRef(null)

      useLayoutEffect(() => {
        const element = stageRef.current
        if (!element) return undefined
        const update = () => {
          const width = element.clientWidth
          const height = element.clientHeight
          setBox((current) =>
            current.width === width && current.height === height ? current : { width, height },
          )
        }
        update()
        if (typeof ResizeObserver === 'function') {
          const observer = new ResizeObserver(update)
          observer.observe(element)
          return () => observer.disconnect()
        }
        window.addEventListener('resize', update)
        return () => window.removeEventListener('resize', update)
      }, [])

      useEffect(() => {
        let stopped = false
        const poll = async () => {
          try {
            const response = await fetch('/zly-studio/mcp/status', { cache: 'no-store' })
            if (!response.ok) return
            const next = await response.json()
            if (!stopped && next && typeof next === 'object') setMcp(next)
          } catch {}
        }
        poll()
        const timer = setInterval(poll, 5000)
        return () => {
          stopped = true
          clearInterval(timer)
        }
      }, [])

      const connectMcp = useCallback(async () => {
        setMcpBusy(true)
        try {
          const response = await fetch('/zly-studio/mcp/start', { method: 'POST' })
          const payload = await response.json()
          if (payload && payload.url) window.open(payload.url, '_blank', 'noopener,noreferrer')
        } catch {}
        setTimeout(() => setMcpBusy(false), 4000)
      }, [])

      const handleMcp = useCallback(async () => {
        if (mcp.connected) {
          try {
            await fetch('/zly-studio/mcp/refresh', { method: 'POST' })
          } catch {}
          return
        }
        await connectMcp()
      }, [mcp.connected, connectMcp])

      const reload = useCallback(() => setNonce((value) => value + 1), [])

      const openExternal = useCallback(() => {
        window.open(base, '_blank', 'noopener,noreferrer')
      }, [base])

      const save = useCallback(() => {
        const next = normalizeUrl(draft)
        storeValue(URL_KEY, next)
        setBase(next)
        setDraft(next)
        setEditing(false)
        setNonce((value) => value + 1)
      }, [draft])

      const toggleMode = useCallback(() => {
        setMode((current) => {
          const next = current === 'fit' ? 'actual' : 'fit'
          storeValue(MODE_KEY, next)
          return next
        })
      }, [])

      const measured = box.width > 0 && box.height > 0
      const scale = mode === 'fit' && measured && box.width < DESKTOP_WIDTH ? box.width / DESKTOP_WIDTH : 1
      const scalePercent = Math.round(scale * 100)
      const frameWidth = measured ? (scale < 1 ? DESKTOP_WIDTH : box.width) : '100%'
      const frameHeight = measured ? box.height / scale : '100%'
      const compact = measured && box.width < 900
      const narrow = measured && box.width < 760

      return h(
        'div',
        { className: 'zly-studio-page' },
        h('style', null, styles),
        h(
          'div',
          { className: 'zly-studio-bar' },
          h(
            'div',
            { className: 'zly-studio-brand' },
            h('span', { className: 'zly-studio-dot', 'aria-hidden': 'true' }),
            h('span', { className: 'zly-studio-title' }, translate('panel.title')),
            compact ? null : h('span', { className: 'zly-studio-sub' }, translate('panel.subtitle')),
          ),
          editing
            ? h(
                'form',
                {
                  className: 'zly-studio-form',
                  onSubmit: (event) => {
                    event.preventDefault()
                    save()
                  },
                },
                h('input', {
                  className: 'zly-studio-input',
                  value: draft,
                  onChange: (event) => setDraft(event.target.value),
                  placeholder: DEFAULT_URL,
                  spellCheck: false,
                  autoFocus: true,
                  'aria-label': translate('settings.title'),
                  title: translate('settings.hint'),
                }),
                h('button', { className: 'zly-studio-btn zly-studio-btn-primary', type: 'submit' }, translate('action.save')),
                h('button', { className: 'zly-studio-btn', type: 'button', onClick: () => { setDraft(base); setEditing(false) } }, translate('action.cancel')),
              )
            : h(
                'div',
                { className: 'zly-studio-actions' },
                narrow ? null : h('span', { className: 'zly-studio-url', title: base }, base.replace(/^https?:\/\//, '')),
                h(
                  'button',
                  {
                    className: 'zly-studio-btn' + (mcp.connected ? ' zly-studio-btn-live' : ''),
                    type: 'button',
                    onClick: handleMcp,
                    title: mcp.connected
                      ? (mcp.expiresAt ? 'MCP 工具已接入，登录令牌约 ' + new Date(mcp.expiresAt).toLocaleTimeString() + ' 刷新' : 'MCP 工具已接入')
                      : (mcp.lastError || '登录工作台并把 MCP 工具接入 DSH'),
                  },
                  mcp.connected ? translate('mcp.connected') : mcpBusy ? translate('mcp.waiting') : translate('mcp.connect'),
                ),
                h(
                  'button',
                  {
                    className: 'zly-studio-btn',
                    type: 'button',
                    onClick: toggleMode,
                    'aria-pressed': mode === 'fit',
                    title: translate(mode === 'fit' ? 'mode.fitHint' : 'mode.actualHint'),
                  },
                  translate(mode === 'fit' ? 'action.fit' : 'action.actual') + (mode === 'fit' ? ' ' + scalePercent + '%' : ''),
                ),
                h('button', { className: 'zly-studio-btn', type: 'button', onClick: () => { setDraft(base); setEditing(true) } }, translate('action.settings')),
                h('button', { className: 'zly-studio-btn', type: 'button', onClick: reload }, translate('action.reload')),
                h('button', { className: 'zly-studio-btn zly-studio-btn-primary', type: 'button', onClick: openExternal }, translate('action.browser')),
              ),
        ),
        h(
          'div',
          { className: 'zly-studio-stage', ref: stageRef },
          h('iframe', {
            key: base + ':' + nonce + ':' + mode,
            className: 'zly-studio-frame',
            src: base,
            title: translate('panel.title'),
            allow: 'clipboard-read; clipboard-write; fullscreen; autoplay; encrypted-media; display-capture',
            referrerPolicy: 'strict-origin-when-cross-origin',
            style: {
              width: frameWidth,
              height: frameHeight,
              transform: scale === 1 ? undefined : 'scale(' + scale + ')',
              transformOrigin: 'top left',
            },
          }),
        ),
      )
    }

    function StudioIcon({ size = 20 }) {
      return h(
        'svg',
        {
          width: size,
          height: size,
          viewBox: '0 0 24 24',
          fill: 'none',
          'aria-hidden': 'true',
          style: { display: 'block' },
        },
        h('rect', {
          x: 3,
          y: 5.5,
          width: 18,
          height: 13,
          rx: 2.5,
          stroke: 'currentColor',
          strokeWidth: 1.6,
        }),
        h('path', {
          d: 'M10.2 9.6v4.8l4.2-2.4-4.2-2.4Z',
          fill: 'currentColor',
        }),
        h('path', {
          d: 'M3.4 9.2h17.2M3.4 14.8h17.2',
          stroke: 'currentColor',
          strokeWidth: 1,
          opacity: 0.45,
        }),
      )
    }

    return {
      inject: ['slots', 'locale'],
      apply(ctx) {
        ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'zly-studio: dictionaries')
        translate = ctx.locale.bind(NS)
        ctx.effect(
          () =>
            ctx.slots.inject('main', () =>
              ctx.slots.register({ name: 'main', key: PANEL_ID, locale: NS }, StudioPage),
            ),
          'zly-studio: main panel',
        )
        ctx.effect(
          () =>
            ctx.slots.inject('sidebar.panellist', () =>
              ctx.slots.register(
                {
                  name: 'sidebar.panellist',
                  id: PANEL_ID,
                  order: 20,
                  locale: NS,
                  label: () => translate('panel.label'),
                },
                StudioIcon,
              ),
            ),
          'zly-studio: sidebar entry',
        )
      },
    }
  },
})
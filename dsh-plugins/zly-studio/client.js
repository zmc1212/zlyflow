window.__ModuleLoader__.load({
  id: 'zly-studio-dsh-plugin',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useCallback, useState } = React

    const NS = 'zly-studio'
    const PANEL_ID = 'zly-studio'
    const URL_KEY = 'zly-studio:base-url'
    const DEFAULT_URL = 'https://comfyui.zlyun168.com'

    const zh = {
      'panel.label': 'ZLY 视频工作台',
      'panel.title': 'ZLY AI 视频工作台',
      'panel.subtitle': '创作 · 导演台 · 任务',
      'action.reload': '重新加载',
      'action.browser': '在浏览器打开',
      'action.settings': '服务地址',
      'action.save': '保存',
      'action.cancel': '取消',
      'settings.title': '工作台服务地址',
      'settings.hint': '默认连接公网部署；本地调试可改为 http://127.0.0.1:7865。',
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
      'settings.title': 'Studio service URL',
      'settings.hint': 'Defaults to the public deployment; use http://127.0.0.1:7865 for local development.',
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

    function readStoredUrl() {
      try {
        return normalizeUrl(localStorage.getItem(URL_KEY) || DEFAULT_URL)
      } catch {
        return DEFAULT_URL
      }
    }

    const styles = `
      .zly-studio-page{display:flex;flex-direction:column;flex:1;height:100%;min-height:0;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary)}
      .zly-studio-bar{flex:none;display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:46px;padding:8px 12px;box-sizing:border-box;border-bottom:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1)}
      .zly-studio-brand{display:flex;align-items:baseline;gap:8px;min-width:0}
      .zly-studio-dot{width:8px;height:8px;border-radius:50%;background:var(--dsw-alias-state-success-primary);flex:none;align-self:center}
      .zly-studio-title{font-size:13px;font-weight:600;white-space:nowrap}
      .zly-studio-sub{font-size:11px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
      .zly-studio-actions{display:flex;align-items:center;gap:8px;min-width:0}
      .zly-studio-url{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--dsw-alias-label-secondary);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
      .zly-studio-btn{appearance:none;box-sizing:border-box;height:28px;padding:0 10px;border-radius:6px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-primary);font-size:12px;line-height:1;cursor:pointer;white-space:nowrap}
      .zly-studio-btn:hover{background:var(--dsw-alias-bg-overlay)}
      .zly-studio-btn:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px}
      .zly-studio-btn-primary{border-color:transparent;background:var(--dsw-alias-brand-primary);color:#ffffff}
      .zly-studio-form{display:flex;align-items:center;gap:8px;min-width:0;flex:1;justify-content:flex-end}
      .zly-studio-input{box-sizing:border-box;height:28px;min-width:220px;max-width:420px;flex:1;padding:0 10px;border-radius:6px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font-size:12px}
      .zly-studio-input:focus{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px;border-color:transparent}
      .zly-studio-frame-wrap{position:relative;display:flex;flex:1;min-height:0}
      .zly-studio-frame{display:block;flex:1;width:100%;height:100%;border:0;background:var(--dsw-alias-bg-base)}
      .zly-studio-hint{flex:none;padding:6px 12px;font-size:11px;color:var(--dsw-alias-label-secondary);border-top:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1)}
    `

    function StudioPage() {
      const [base, setBase] = useState(readStoredUrl)
      const [draft, setDraft] = useState(base)
      const [nonce, setNonce] = useState(0)
      const [editing, setEditing] = useState(false)

      const reload = useCallback(() => setNonce((value) => value + 1), [])

      const openExternal = useCallback(() => {
        window.open(base, '_blank', 'noopener,noreferrer')
      }, [base])

      const save = useCallback(() => {
        const next = normalizeUrl(draft)
        try {
          localStorage.setItem(URL_KEY, next)
        } catch {}
        setBase(next)
        setDraft(next)
        setEditing(false)
        setNonce((value) => value + 1)
      }, [draft])

      const startEditing = useCallback(() => {
        setDraft(base)
        setEditing(true)
      }, [base])

      const cancelEditing = useCallback(() => {
        setDraft(base)
        setEditing(false)
      }, [base])

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
            h('span', { className: 'zly-studio-sub' }, translate('panel.subtitle')),
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
                h('button', { className: 'zly-studio-btn', type: 'button', onClick: cancelEditing }, translate('action.cancel')),
              )
            : h(
                'div',
                { className: 'zly-studio-actions' },
                h('span', { className: 'zly-studio-url', title: base }, base.replace(/^https?:\/\//, '')),
                h('button', { className: 'zly-studio-btn', type: 'button', onClick: startEditing }, translate('action.settings')),
                h('button', { className: 'zly-studio-btn', type: 'button', onClick: reload }, translate('action.reload')),
                h('button', { className: 'zly-studio-btn zly-studio-btn-primary', type: 'button', onClick: openExternal }, translate('action.browser')),
              ),
        ),
        h(
          'div',
          { className: 'zly-studio-frame-wrap' },
          h('iframe', {
            key: base + ':' + nonce,
            className: 'zly-studio-frame',
            src: base,
            title: translate('panel.title'),
            allow: 'clipboard-read; clipboard-write; fullscreen; autoplay; encrypted-media; display-capture',
            referrerPolicy: 'strict-origin-when-cross-origin',
          }),
        ),
        h('div', { className: 'zly-studio-hint' }, translate('settings.hint')),
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
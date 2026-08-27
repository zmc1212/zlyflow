async (page) => {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    let body = {}
    if (url.endsWith('/api/auth/status')) {
      body = { setup_required: false, authenticated: true, csrf_token: 'mock-csrf', user: { id: 'visual-user', username: 'visual', display_name: '视觉验收', role: 'employee', is_active: true, must_change_password: false, created_at: '', updated_at: '' } }
    } else if (url.endsWith('/api/jobs')) body = []
    else if (url.endsWith('/api/modes')) body = []
    else if (url.endsWith('/api/storage')) body = { provider: 'browser-local', requires_local_directory: false }
    else if (url.endsWith('/api/health')) body = { comfy: { reachable: false }, grs: { available: false, message: '视觉验收模拟' } }
    else if (url.endsWith('/api/llm/status')) body = { available: false, supports_vision: false, message: '视觉验收模拟' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.reload()
  await page.waitForTimeout(1200)
}

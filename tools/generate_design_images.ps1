# 用 codex exec 生成导演台设计图（当前优先：17-25 Agent 剧本创作模式）
# 用法: powershell -ExecutionPolicy Bypass -File tools\generate_design_images.ps1
# 已有 PNG 的编号会自动跳过；如需强制重生成，先删除 docs\导演台设计图\ 下对应文件。
# 01-11（导演台其他页面）暂缓：需要时把对应编号加回 $refMap（提示词文件已在 dev-log\codex-prompts\）。

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path "docs\导演台设计图" | Out-Null

# 编号 -> 参考截图（结构对照用）
$refMap = [ordered]@{
  "17" = "docs/design-ref-director/17-script-agent-regen.png"
  "18" = "docs/design-ref-director/18-regenerate-confirm.png"
  "19" = "docs/design-ref-director/19-clarify-planning.png"
  "20" = "docs/design-ref-director/20-clarify-card.png"
  "21" = "docs/design-ref-director/21-script-streaming.png"
  "22" = "docs/design-ref-director/22-stage-clarify-art-style.png"
  "23" = "docs/design-ref-director/23-storyboard-streaming.png"
  "24" = "docs/design-ref-director/24-storyboard-shotgrid.png"
  "25" = "docs/design-ref-director/25-script-complete.png"
}

foreach ($num in $refMap.Keys) {
  $existing = Get-ChildItem "docs\导演台设计图" -Filter "$num-*.png" -ErrorAction SilentlyContinue
  if ($existing) { Write-Host "[$num] 已存在，跳过"; continue }
  $ref = $refMap[$num]
  if (-not (Test-Path $ref)) { Write-Host "[$num] 参考截图缺失（$ref），跳过"; continue }
  Write-Host "[$num] 生成中（参考图 $ref，模型 gpt-5.6-luna）..."
  Get-Content "dev-log\codex-prompts\$num.txt" -Encoding UTF8 |
    codex exec -m gpt-5.6-luna --cd . -c sandbox_mode="workspace-write" -i $ref - 2>&1 |
      Tee-Object -FilePath "dev-log\codex-prompts\$num.run.log"
  Write-Host "[$num] exit=$LASTEXITCODE"
}

Write-Host "完成。产物目录: docs\导演台设计图\"
Get-ChildItem "docs\导演台设计图" | Format-Table Name, Length

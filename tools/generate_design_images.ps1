# 用 codex exec 补跑导演台设计图（额度重置后运行）
# 用法: powershell -ExecutionPolicy Bypass -File tools\generate_design_images.ps1
# 已有 PNG 的编号会自动跳过；如需强制重生成，先删除 docs\导演台设计图\ 下对应文件。

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path "docs\导演台设计图" | Out-Null

# 编号 -> 参考截图（结构对照用）
$refMap = @{
  "02" = "docs/design-ref-director/02-script-hero.png"
  "03" = "docs/design-ref-director/02-script-hero.png"
  "04" = "docs/design-ref-director/02-script-hero.png"
  "05" = "docs/design-ref-director/03-art-style.png"
  "06" = "docs/design-ref-director/11-storyboard-shots.png"
  "07" = "docs/design-ref-director/12-shots-populated.png"
  "08" = "docs/design-ref-director/09-export.png"
  "09" = "docs/design-ref-director/10-timeline.png"
  "10" = "docs/design-ref-director/13-batch-studio.png"
  "11" = "docs/design-ref-director/14-replication-studio.png"
}

foreach ($num in ($refMap.Keys | Sort-Object)) {
  $existing = Get-ChildItem "docs\导演台设计图" -Filter "$num-*.png" -ErrorAction SilentlyContinue
  if ($existing) { Write-Host "[$num] 已存在，跳过"; continue }
  $ref = $refMap[$num]
  Write-Host "[$num] 生成中（参考图 $ref）..."
  Get-Content "dev-log\codex-prompts\$num.txt" -Encoding UTF8 |
    codex exec --cd . -c sandbox_mode="workspace-write" -i $ref - 2>&1 |
      Tee-Object -FilePath "dev-log\codex-prompts\$num.run.log"
  Write-Host "[$num] exit=$LASTEXITCODE"
}

Write-Host "完成。产物目录: docs\导演台设计图\"
Get-ChildItem "docs\导演台设计图" | Format-Table Name, Length

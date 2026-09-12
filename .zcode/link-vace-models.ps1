$ErrorActionPreference = 'Stop'
$root = 'D:\zlyun\Toonflow\整合包及模型\comfyui-integrate-v1.3\comfyui-integrate'
$src  = Join-Path $root 'vace-native-checkpoint'
$pairs = @(
    @{ Link = Join-Path $root 'Comfyui\models\diffusion_models\wan2.1_vace_1.3B.safetensors'; Target = Join-Path $src 'diffusion_pytorch_model.safetensors' },
    @{ Link = Join-Path $root 'Comfyui\models\text_encoders\umt5_xxl_enc_bf16.pth'; Target = Join-Path $src 'models_t5_umt5-xxl-enc-bf16.pth' },
    @{ Link = Join-Path $root 'Comfyui\models\vae\wan_2.1_vae.pth'; Target = Join-Path $src 'Wan2.1_VAE.pth' }
)
foreach ($pair in $pairs) {
    if (Test-Path $pair.Link) { Write-Output "EXISTS: $($pair.Link)"; continue }
    New-Item -ItemType HardLink -Path $pair.Link -Target $pair.Target | Out-Null
    Write-Output "LINKED: $($pair.Link)"
}

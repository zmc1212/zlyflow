Add-Type -AssemblyName System.Net.Http

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$apiUrl = 'http://127.0.0.1:7865/api/jobs'
$ffmpeg = 'G:\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe'
$logPath = Join-Path $workspace 'results\zly_ai_video_studio_sasuke_gojo_chain.log'
$options = '{"aspect_ratio":"16:9","megapixels":0.2,"duration":5}'
$sasukeReference = Join-Path $workspace 'results\zly_ai_video_studio_sasuke_ref.png'
$gojoReference = Join-Path $workspace 'results\zly_ai_video_studio_gojo_ref.png'

function Write-ChainLog([string]$message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Add-Content -LiteralPath $logPath -Encoding UTF8
}

function Submit-R2V([string]$prompt, [string[]]$references) {
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    $utf8 = [Text.Encoding]::UTF8
    $form.Add([System.Net.Http.StringContent]::new('minimax-h3-r2v', $utf8), 'mode')
    $form.Add([System.Net.Http.StringContent]::new($prompt, $utf8), 'prompt')
    $form.Add([System.Net.Http.StringContent]::new($options, $utf8), 'options')
    $files = [System.Collections.Generic.List[System.Net.Http.StreamContent]]::new()
    $client = [System.Net.Http.HttpClient]::new()
    try {
        foreach ($reference in $references) {
            $file = [System.Net.Http.StreamContent]::new([IO.File]::OpenRead($reference))
            $files.Add($file)
            $form.Add($file, 'references', [IO.Path]::GetFileName($reference))
        }
        $response = $client.PostAsync($apiUrl, $form).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Task submission failed: $($response.StatusCode) $($response.Content.ReadAsStringAsync().GetAwaiter().GetResult())"
        }
        return $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    }
    finally {
        $client.Dispose()
        $form.Dispose()
    }
}

function Wait-ForJob([string]$jobId) {
    do {
        Start-Sleep -Seconds 10
        $job = Invoke-RestMethod "$apiUrl/$jobId"
        Write-ChainLog "job=$jobId status=$($job.status) progress=$($job.progress)"
    } while ($job.status -in @('queued', 'running'))
    if ($job.status -ne 'succeeded') {
        throw "Job $jobId ended with status $($job.status): $($job.error)"
    }
    return $job
}

function Output-VideoPath($job) {
    $video = ($job.outputs | Where-Object kind -eq 'video' | Select-Object -First 1).path
    if (-not $video) { throw "Job $($job.id) has no video output" }
    return Join-Path $workspace "results\$video"
}

function Extract-EndFrame([string]$videoPath, [int]$segment) {
    $framePath = Join-Path $workspace ("results\zly_ai_video_studio_sasuke_gojo_s{0:D2}_end.png" -f $segment)
    & $ffmpeg -hide_banner -loglevel error -sseof -0.08 -i $videoPath -frames:v 1 $framePath -y
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $framePath)) {
        throw "Could not extract end frame from $videoPath"
    }
    return $framePath
}

if (-not (Test-Path -LiteralPath $sasukeReference) -or -not (Test-Path -LiteralPath $gojoReference)) {
    throw 'Sasuke or Gojo reference image is missing.'
}

$beats = @(
    'Create a 5-second cinematic 2D anime crossover scene in the dramatic, lantern-lit indoor atmosphere of an anime battle parody. <Picture 1> is Uchiha Sasuke: preserve his black spiky hair, pale face, stern eyes, light gray high collar, and blue-black shinobi clothing. <Picture 2> is Satoru Gojo: preserve his white spiky hair, black blindfold, black high-collar uniform, and confident posture. In a giant dark wooden hall filled with warm orange lanterns, Sasuke and Gojo stand ten meters apart in a tense medium-wide two-shot. Begin low and wide, slowly push in as Sasuke raises one hand and faint blue-violet lightning collects at his fingers; Gojo smiles and adjusts his blindfold. Clean cel shading, sharp line art, warm amber versus cool blue lighting, anime action sound effects only, no subtitles, no text, no watermark, no logos.',
    'Continue the same Sasuke-versus-Gojo scene. <Picture 1> is the previous shot ending and must be matched for composition, lantern hall, lighting, and character continuity. <Picture 2> is Uchiha Sasuke and locks his face, black spiky hair, gray high collar, and shinobi outfit. <Picture 3> is Satoru Gojo and locks his white hair, blindfold, and black uniform. Over 5 seconds, orbit from behind Sasuke to reveal his left eye glowing purple while blue lightning coils around his arm. Gojo calmly extends one open hand; the space between them bends with rippling blue-white distortion. Keep both faces recognizable, motion readable, no impact yet. High-quality 2D anime battle cinematography, no subtitles, no text, no watermark, no logos.',
    'Continue directly from the supplied visual references. <Picture 1> is the previous shot ending and defines the exact scene continuity. <Picture 2> is Uchiha Sasuke and must remain recognizably Sasuke. <Picture 3> is Satoru Gojo and must remain recognizably Gojo. Over 5 seconds, cut to a close-up of Sasuke forming a hand sign; behind him a restrained translucent purple armored spectral silhouette appears. Cut back to Gojo as he lifts his blindfold slightly and a precise blue energy sphere forms over his fingertips. Use one quick anime-style whip pan between the two close-ups, then settle on a balanced two-person medium shot. Lanterns flicker from the energy pressure. No subtitles, no text, no watermark, no logos.',
    'Continue from the supplied final-frame reference. <Picture 1> is the previous shot ending and must preserve the same lantern hall, pose continuity, and color grade. <Picture 2> locks Uchiha Sasuke. <Picture 3> locks Satoru Gojo. Over 5 seconds, Sasuke and Gojo release their techniques toward the center without showing gore or destruction: violet lightning and blue-white spatial energy meet, then dissolve into drifting embers. The camera pulls back to a heroic final wide shot where both stand intact on opposite sides of the hall, framed by warm lanterns and cool blue light. Hold the last 0.8 seconds cleanly with headroom for later titles. Cinematic cel-shaded anime action, no subtitles, no text, no watermark, no logos.'
)

$videos = [System.Collections.Generic.List[string]]::new()
$job = Submit-R2V $beats[0] @($sasukeReference, $gojoReference)
Write-ChainLog "Submitted segment 1 job=$($job.id)"
$completed = Wait-ForJob $job.id
$videoPath = Output-VideoPath $completed
$videos.Add($videoPath)
$frame = Extract-EndFrame $videoPath 1
Write-ChainLog "Completed segment 1 video=$([IO.Path]::GetFileName($videoPath)) end_frame=$frame"

for ($index = 1; $index -lt $beats.Count; $index++) {
    $segment = $index + 1
    $job = Submit-R2V $beats[$index] @($frame, $sasukeReference, $gojoReference)
    Write-ChainLog "Submitted segment $segment job=$($job.id) using $frame"
    $completed = Wait-ForJob $job.id
    $videoPath = Output-VideoPath $completed
    $videos.Add($videoPath)
    $frame = Extract-EndFrame $videoPath $segment
    Write-ChainLog "Completed segment $segment video=$([IO.Path]::GetFileName($videoPath)) end_frame=$frame"
}

$concatList = Join-Path $workspace 'results\zly_ai_video_studio_sasuke_gojo_concat.txt'
$videos | ForEach-Object { "file '$($_.Replace("'", "''"))'" } | Set-Content -LiteralPath $concatList -Encoding ascii
$finalPath = Join-Path $workspace 'results\zly_ai_video_studio_sasuke_gojo_20s.mp4'
& $ffmpeg -hide_banner -loglevel error -f concat -safe 0 -i $concatList -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k -movflags +faststart $finalPath -y
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $finalPath)) {
    throw 'Could not concatenate the four video segments.'
}
Write-ChainLog "Completed final video=$finalPath"
Write-Output "Final video: $finalPath"

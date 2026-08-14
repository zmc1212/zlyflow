param(
    [string]$FirstJobId
)

Add-Type -AssemblyName System.Net.Http

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$apiUrl = 'http://127.0.0.1:7865/api/jobs'
$ffmpeg = 'G:\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe'
$logPath = Join-Path $workspace 'results\zly_ai_video_studio_crossover_chain.log'
$options = '{"aspect_ratio":"16:9","megapixels":0.2,"duration":5}'

function Write-ChainLog([string]$message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Add-Content -LiteralPath $logPath -Encoding UTF8
}

function Submit-T2V([string]$prompt) {
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    $utf8 = [Text.Encoding]::UTF8
    $form.Add([System.Net.Http.StringContent]::new('minimax-h3-t2v', $utf8), 'mode')
    $form.Add([System.Net.Http.StringContent]::new($prompt, $utf8), 'prompt')
    $form.Add([System.Net.Http.StringContent]::new($options, $utf8), 'options')
    $client = [System.Net.Http.HttpClient]::new()
    try {
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

function Submit-I2V([string]$prompt, [string]$framePath) {
    $form = [System.Net.Http.MultipartFormDataContent]::new()
    $utf8 = [Text.Encoding]::UTF8
    $form.Add([System.Net.Http.StringContent]::new('minimax-h3-i2v', $utf8), 'mode')
    $form.Add([System.Net.Http.StringContent]::new($prompt, $utf8), 'prompt')
    $form.Add([System.Net.Http.StringContent]::new($options, $utf8), 'options')
    $file = [System.Net.Http.StreamContent]::new([IO.File]::OpenRead($framePath))
    $form.Add($file, 'references', [IO.Path]::GetFileName($framePath))
    $client = [System.Net.Http.HttpClient]::new()
    try {
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

function Extract-EndFrame([string]$videoName, [int]$segment) {
    $videoPath = Join-Path $workspace "results\$videoName"
    $framePath = Join-Path $workspace ("results\zly_ai_video_studio_crossover_s{0:D2}_end.png" -f $segment)
    & $ffmpeg -hide_banner -loglevel error -sseof -0.08 -i $videoPath -frames:v 1 $framePath -y
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $framePath)) {
        throw "Could not extract end frame from $videoName"
    }
    return $framePath
}

function Output-VideoPath($job) {
    $video = ($job.outputs | Where-Object kind -eq 'video' | Select-Object -First 1).path
    if (-not $video) { throw "Job $($job.id) has no video output" }
    return Join-Path $workspace "results\$video"
}

$beats = @(
    'Create a 5-second original 2D anime action-parody short, 16:9. In a vast moonlit shrine hall filled with warm orange lanterns, a tall long-haired armored warlord with a crimson battle fan faces a white-haired sorcerer in a black high-collar coat. A raven-cloaked illusionist watches from a balcony, and a young lightning swordsman is only a silhouette in the far background. Establish the absurd crossover standoff with a low-angle wide shot, then push to a charged two-person medium shot. Wind stirs the banners; blue sparks and red ember particles gather but no impact happens yet. Crisp cel shading, controlled line art, cinematic anime compositing, dramatic Japanese-style action sound design, no subtitles, no text, no watermark, no logos.',
    'Continue directly from the supplied first frame. Keep the shrine hall, warm orange lantern lighting, character designs, armor, clothing, and 2D cel-shaded anime style identical. Over 5 seconds, the long-haired armored warlord opens his crimson battle fan and a translucent giant guardian silhouette rises behind him. The white-haired sorcerer calmly lifts one hand, blue-white spatial energy bends the lantern light around him. Start over the sorcerer''s shoulder, then orbit to a tense two-shot. The raven-cloaked illusionist remains on the balcony. Fast but readable effects, stable faces and hands, no subtitles, no text, no watermark, no logos.',
    'Continue directly from the supplied first frame. Preserve all characters and the lantern-lit shrine hall exactly. Over 5 seconds, cut to the raven-cloaked illusionist in close-up; he opens one glowing red eye and releases a thin spiral of black flame that curls harmlessly around the giant guardian''s shield. The white-haired sorcerer turns his head toward the balcony with a faint amused smile, while the armored warlord stays poised in the foreground. Use a quick rack focus from the black flame to the eye, then a dramatic lateral camera slide. High-energy original anime crossover parody, cel shading, dark flame and red embers, no subtitles, no text, no watermark, no logos.',
    'Continue directly from the supplied first frame. Preserve the same characters, shrine hall, orange lanterns, anime line work, and effects palette. Over 5 seconds, the young lightning swordsman lands between the two rivals in a burst of violet electricity. The sorcerer and armored warlord lower their hands for one beat, glance at the new arrival, then all three turn toward an unseen threat outside the hall. Pull back to a heroic wide composition with the translucent guardian, blue spatial ripples, black flame, and violet lightning layered in depth. End on a clean held group tableau with empty space at the top for later editing. Original cinematic 2D anime action parody, no subtitles, no text, no watermark, no logos.'
)

$videos = [System.Collections.Generic.List[string]]::new()
$first = if ($FirstJobId) { @{ id = $FirstJobId } } else { Submit-T2V $beats[0] }
if ($FirstJobId) {
    Write-ChainLog "Resuming submitted segment 1 job=$FirstJobId"
}
else {
    Write-ChainLog "Submitted segment 1 job=$($first.id)"
}
$completed = Wait-ForJob $first.id
$videoPath = Output-VideoPath $completed
$videos.Add($videoPath)
$frame = Extract-EndFrame ([IO.Path]::GetFileName($videoPath)) 1
Write-ChainLog "Completed segment 1 video=$([IO.Path]::GetFileName($videoPath)) end_frame=$frame"

for ($index = 1; $index -lt $beats.Count; $index++) {
    $segment = $index + 1
    $job = Submit-I2V $beats[$index] $frame
    Write-ChainLog "Submitted segment $segment job=$($job.id) using $frame"
    $completed = Wait-ForJob $job.id
    $videoPath = Output-VideoPath $completed
    $videos.Add($videoPath)
    $frame = Extract-EndFrame ([IO.Path]::GetFileName($videoPath)) $segment
    Write-ChainLog "Completed segment $segment video=$([IO.Path]::GetFileName($videoPath)) end_frame=$frame"
}

$concatList = Join-Path $workspace 'results\zly_ai_video_studio_crossover_concat.txt'
$videos | ForEach-Object { "file '$($_.Replace("'", "''"))'" } | Set-Content -LiteralPath $concatList -Encoding ascii
$finalPath = Join-Path $workspace 'results\zly_ai_video_studio_crossover_20s.mp4'
& $ffmpeg -hide_banner -loglevel error -f concat -safe 0 -i $concatList -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k -movflags +faststart $finalPath -y
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $finalPath)) {
    throw 'Could not concatenate the four video segments.'
}
Write-ChainLog "Completed final video=$finalPath"
Write-Output "Final video: $finalPath"

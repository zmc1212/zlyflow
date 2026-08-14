Add-Type -AssemblyName System.Net.Http

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$apiUrl = 'http://127.0.0.1:7865/api/jobs'
$ffmpeg = 'G:\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe'
$logPath = Join-Path $workspace 'results\zly_ai_video_studio_train_chain.log'
$options = '{"aspect_ratio":"16:9","megapixels":0.2,"duration":5}'

function Write-ChainLog([string]$message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Add-Content -LiteralPath $logPath -Encoding UTF8
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
    $videoPath = Join-Path $workspace "results\\$videoName"
    $framePath = Join-Path $workspace ("results\\zly_ai_video_studio_train_s{0:D2}_end.png" -f $segment)
    & $ffmpeg -hide_banner -loglevel error -sseof -0.08 -i $videoPath -frames:v 1 $framePath -y
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $framePath)) {
        throw "Could not extract end frame from $videoName"
    }
    return $framePath
}

$beats = @(
    'Continue directly from the supplied first frame. Keep the same woman, child, mother, train carriage, lighting, wardrobe, and realistic style. Over 5 seconds, the mother stands in the aisle with an impatient, dismissive expression after hearing the request. The woman remains seated at first, looks up steadily, and calmly explains that the seat is being kicked repeatedly. Start with a medium-wide two-person composition, then slowly push toward the woman. The child stays in the background. Natural restrained acting, stable faces and hands, no subtitles, no text, no watermark, no logos, no physical conflict.',
    'Continue directly from the supplied first frame. Keep all characters and the train carriage identical. Over 5 seconds, the woman rises slowly into the aisle, upright but non-threatening, and clearly states a boundary: the child must stop disturbing other passengers or she will ask a train attendant for help. The mother is surprised and loses her dismissive posture. Use an over-the-shoulder shot followed by a stable two-person medium shot. The child becomes quiet. Natural realistic acting, no subtitles, no text, no watermark, no logos, no physical conflict.',
    'Continue directly from the supplied first frame. Keep the same characters, clothing, carriage, and daylight. Over 5 seconds, the mother looks at the child and notices that the child has stopped. Her expression changes from defensive to embarrassed; she gently signals the child to sit properly. The woman relaxes her shoulders and takes one small step back. Start with the child in focus, then rack focus to the mother. Natural small movements, no subtitles, no text, no watermark, no logos, no physical conflict.',
    'Continue directly from the supplied first frame. Keep visual continuity exact. Over 5 seconds, the mother quietly corrects the child and makes a restrained apologetic gesture toward the woman. The woman nods once and returns toward her seat. The child sits still with hands in lap. Use a calm medium-wide composition and slow lateral camera movement. Realistic social drama, no subtitles, no text, no watermark, no logos, no physical conflict.',
    'Continue directly from the supplied first frame. Keep visual continuity exact. Over 5 seconds, the woman sits again by the window and places her beige canvas bag neatly beside her. The mother remains attentive behind her, the child is quiet, and the tension fades. The camera moves from a side medium shot to a gentle close-up of the woman breathing out and looking toward the window. Natural restrained expression, no subtitles, no text, no watermark, no logos, no physical conflict.',
    'Continue directly from the supplied first frame. Keep all characters, wardrobe, train carriage, and daylight identical. Over 5 seconds, the train continues smoothly. The woman opens a book and settles into a calm expression; behind her, mother and child sit quietly. Slowly pull back to a peaceful wide view of the carriage, leaving a reflective ending. Realistic cinematic social drama, no subtitles, no text, no watermark, no logos, no physical conflict.'
)

$frame = Join-Path $workspace 'results\zly_ai_video_studio_train_s02_end.png'
for ($offset = 0; $offset -lt $beats.Count; $offset++) {
    $segment = $offset + 3
    Write-ChainLog "Submitting segment $segment using $frame"
    $job = Submit-I2V $beats[$offset] $frame
    Write-ChainLog "Submitted segment $segment job=$($job.id)"
    $completed = Wait-ForJob $job.id
    $video = ($completed.outputs | Where-Object kind -eq 'video' | Select-Object -First 1).path
    if (-not $video) { throw "Segment $segment has no video output" }
    $frame = Extract-EndFrame $video $segment
    Write-ChainLog "Completed segment $segment video=$video end_frame=$frame"
}

Write-ChainLog 'All eight train-drama segments completed.'
